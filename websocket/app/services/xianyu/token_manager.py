"""
Token管理模块

功能:
1. Token刷新循环
2. Cookie刷新循环
3. 浏览器Cookie刷新
4. Token验证
"""
import asyncio
import time
from loguru import logger

# Token 刷新未成功、且原因在平台风控侧的状态值（refresh_token 的
# last_token_refresh_status）。命中这些状态才累计风控退避；网络/超时等
# 普通失败不累计（那不是风控，退避反而耽误恢复）。
RISK_FAIL_STATUSES = frozenset({
    "failed_captcha_max_retries",  # 滑块重试达上限仍未过
    "failed_captcha",  # 滑块验证失败
    "failed_captcha_exception",  # 滑块处理异常
    "failed_risk_log_create",  # 风控日志创建失败（接口已返回风控信号）
    "skipped_risk_control_processing",  # 同账号已有处理中的风控任务
    "skipped_risk_control_check_failed",  # 风控检查失败
    "skipped_local_slider_disabled",  # 本机滑块不处理已开启（接口仍需滑块）
    "skipped_local_slider_config_unavailable",  # 滑块开关读取失败
})

# 连续风控失败的刷新间隔退避阶梯（秒）：第 1 次失败起 5 分钟，第 2 次 15 分钟，
# 第 3 次起 30 分钟封顶。账号被平台长时间标记时（实测有持续 5 小时的），
# 避免仍按正常间隔（默认 3 分钟）高频空撞接口、加重风控。
RISK_BACKOFF_STEPS = (300, 900, 1800)


def risk_backoff_interval(fail_streak: int) -> int:
    """按连续风控失败周期数计算退避间隔（秒）。

    Args:
        fail_streak: 连续因风控未刷到 Token 的周期数，<=0 表示正常（无退避）。

    Returns:
        int: 本轮应使用的刷新间隔秒数；fail_streak 超过阶梯长度时封顶。
    """
    if fail_streak <= 0:
        return 0
    return RISK_BACKOFF_STEPS[min(fail_streak, len(RISK_BACKOFF_STEPS)) - 1]


class TokenManager:
    """Token管理器"""
    
    def __init__(self, xianyu_instance):
        """
        初始化Token管理器
        
        Args:
            xianyu_instance: XianyuAsync实例的引用
        """
        self.xianyu = xianyu_instance
        self.cookie_id = xianyu_instance.cookie_id
        
        # Token配置
        self.token_refresh_interval = xianyu_instance.token_refresh_interval
        self.token_retry_interval = xianyu_instance.token_retry_interval
        self.last_token_refresh_time = 0
        self.current_token = None
        
        # Cookie刷新配置
        self.cookie_refresh_interval = 180  # 3分钟
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_lock = asyncio.Lock()
        self.cookie_refresh_enabled = True

        # 风控退避状态：连续因风控未刷到 Token 的周期数（0=正常），
        # 以及正常刷新间隔（退避解除时恢复）。cookie_refresh_interval 会在
        # 风控期间被动态调大，见 _apply_refresh_outcome。
        self.risk_fail_streak = 0
        self.normal_cookie_refresh_interval = self.cookie_refresh_interval
        
        # 消息接收标识 - 用于控制Cookie刷新
        self.last_message_received_time = 0
        self.message_cookie_refresh_cooldown = 300  # 收到消息后5分钟内不执行Cookie刷新
        
        # 扫码登录Cookie刷新标志
        self.last_qr_cookie_refresh_time = 0
        self.qr_cookie_refresh_cooldown = 600  # 扫码登录Cookie刷新后的冷却时间:10分钟
        
        # 浏览器Cookie刷新成功标志
        self.browser_cookie_refreshed = False
        self.restarted_in_browser_refresh = False
    
    async def token_refresh_loop(self):
        """Token刷新循环"""
        try:
            while True:
                try:
                    await self.xianyu._interruptible_sleep(self.token_refresh_interval)
                    
                    if time.time() - self.last_token_refresh_time >= self.token_refresh_interval:
                        await self.xianyu.refresh_token()
                        
                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】Token刷新循环收到取消信号")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】Token刷新循环异常: {str(e)}")
                    await self.xianyu._interruptible_sleep(self.token_retry_interval)
                    
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】Token刷新循环已取消")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】Token刷新循环已退出")
    
    async def cookie_refresh_loop(self):
        """Cookie刷新定时任务"""
        logger.info(f"【{self.cookie_id}】Cookie刷新循环已启动，刷新间隔: {self.cookie_refresh_interval}秒")
        check_count = 0
        try:
            while True:
                try:
                    check_count += 1
                    if not self.cookie_refresh_enabled:
                        logger.debug(f"【{self.cookie_id}】Cookie刷新功能已禁用,跳过执行")
                        await self.xianyu._interruptible_sleep(300)
                        continue

                    current_time = time.time()
                    time_since_last_refresh = current_time - self.last_cookie_refresh_time
                    
                    # 每10次检查输出一次状态日志（约10分钟）
                    if check_count % 10 == 0:
                        logger.info(f"【{self.cookie_id}】Cookie刷新状态: 距上次刷新 {int(time_since_last_refresh)}秒，间隔 {self.cookie_refresh_interval}秒")
                    
                    if time_since_last_refresh >= self.cookie_refresh_interval:
                        time_since_last_message = current_time - self.last_message_received_time
                        if self.last_message_received_time > 0 and time_since_last_message < self.message_cookie_refresh_cooldown:
                            remaining_time = self.message_cookie_refresh_cooldown - time_since_last_message
                            logger.info(f"【{self.cookie_id}】收到消息后冷却中,还需等待 {int(remaining_time)}秒")
                        elif self.cookie_refresh_lock.locked():
                            logger.info(f"【{self.cookie_id}】Cookie刷新任务已在执行中,跳过本次触发")
                        else:
                            logger.info(f"【{self.cookie_id}】开始执行Cookie刷新任务...")
                            await self._execute_cookie_refresh(current_time)

                    await self.xianyu._interruptible_sleep(60)
                    
                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】Cookie刷新循环收到取消信号,准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】Cookie刷新循环失败: {str(e)}")
                    await self.xianyu._interruptible_sleep(60)
                    
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】Cookie刷新循环已取消")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】Cookie刷新循环已退出")
    
    def _apply_refresh_outcome(self, *, succeeded: bool, status: str) -> None:
        """按本轮刷新的最终结果调整风控退避状态。

        成功（含缓存命中）：解除退避，间隔恢复正常；
        风控类失败：连续周期数 +1，间隔按阶梯拉长（5/15/30 分钟封顶）；
        其他失败（网络/超时等）：不累计，保持正常间隔。

        Args:
            succeeded: 本轮是否最终拿到了 Token。
            status: xianyu.last_token_refresh_status 的最终值。
        """
        if succeeded:
            if self.risk_fail_streak > 0:
                logger.info(
                    f"【{self.cookie_id}】风控退避解除：刷新成功，"
                    f"恢复正常刷新间隔 {self.normal_cookie_refresh_interval} 秒"
                )
            self.risk_fail_streak = 0
            self.cookie_refresh_interval = self.normal_cookie_refresh_interval
            return
        if status in RISK_FAIL_STATUSES:
            self.risk_fail_streak += 1
            self.cookie_refresh_interval = risk_backoff_interval(self.risk_fail_streak)
            logger.warning(
                f"【{self.cookie_id}】连续第 {self.risk_fail_streak} 个周期因风控未刷到Token，"
                f"刷新间隔已退避至 {self.cookie_refresh_interval} 秒（避免高频空撞加重风控）"
            )

    async def _execute_cookie_refresh(self, current_time: float):
        """
        执行Cookie刷新任务
        
        Args:
            current_time: 当前时间戳
        """
        async with self.cookie_refresh_lock:
            try:
                logger.info(f"【{self.cookie_id}】开始Cookie刷新任务...")
                
                new_token = await self.xianyu.refresh_token()

                if new_token:
                    self.last_cookie_refresh_time = current_time
                    self._apply_refresh_outcome(succeeded=True, status="success")
                    logger.info(f"【{self.cookie_id}】Cookie刷新任务完成,Token已更新")
                elif getattr(self.xianyu, "last_token_refresh_status", "") in (
                    "skipped_local_slider_disabled",
                    "skipped_local_slider_config_unavailable",
                    "skipped_risk_control_processing",
                    "skipped_risk_control_check_failed",
                    "skipped_startup_cache_lookup_failed",
                ):
                    self.last_cookie_refresh_time = time.time()
                    refresh_status = self.xianyu.last_token_refresh_status
                    self._apply_refresh_outcome(succeeded=False, status=refresh_status)
                    if refresh_status == "skipped_local_slider_disabled":
                        reason = "Token接口仍需滑块，但本机滑块不处理已开启"
                    elif refresh_status == "skipped_local_slider_config_unavailable":
                        reason = "本机滑块处理开关读取失败"
                    elif refresh_status == "skipped_risk_control_processing":
                        reason = "同账号已有处理中的风控任务"
                    elif refresh_status == "skipped_startup_cache_lookup_failed":
                        reason = "启动阶段读取Token缓存失败"
                    else:
                        reason = "处理中风控日志检查失败"
                    logger.warning(
                        f"【{self.cookie_id}】{reason}，"
                        f"等待下一个{self.cookie_refresh_interval}秒刷新周期"
                    )
                else:
                    logger.warning(f"【{self.cookie_id}】Cookie刷新任务失败,Token刷新未成功，5秒后立即重试")
                    # 失败后不更新 last_cookie_refresh_time，等待5秒后立即重试
                    await self.xianyu._interruptible_sleep(5)
                    logger.info(f"【{self.cookie_id}】开始重试Cookie刷新任务...")
                    retry_token = await self.xianyu.refresh_token()
                    if retry_token:
                        self.last_cookie_refresh_time = time.time()
                        self._apply_refresh_outcome(succeeded=True, status="success")
                        logger.info(f"【{self.cookie_id}】Cookie刷新重试成功,Token已更新")
                    else:
                        logger.warning(f"【{self.cookie_id}】Cookie刷新重试仍失败,等待下一个刷新周期")
                        self.last_cookie_refresh_time = time.time()
                        self._apply_refresh_outcome(
                            succeeded=False,
                            status=getattr(self.xianyu, "last_token_refresh_status", ""),
                        )
                    
            except Exception as e:
                logger.error(f"【{self.cookie_id}】执行Cookie刷新任务异常: {str(e)}")
                self.last_cookie_refresh_time = time.time()
            finally:
                self.last_message_received_time = 0
