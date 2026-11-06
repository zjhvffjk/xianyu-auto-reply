# 批量发布异常恢复实施计划

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 核查结果正常返回，单项未知不阻断剩余商品，历史暂停任务可手动继续。

**Architecture:** 沿用现有行锁和 pending 队列；unknown 永不重新领取。只在没有待发布项时将仍有未知结果的批次留在 attention。

**Tech Stack:** Python、SQLAlchemy AsyncSession、MySQL、React、TypeScript。

**Spec:** ../specs/2026-11-07-batch-publish-recovery-design.md

## Global Constraints

不真实发布；不改线上记录；不混入拼多多；保留 c4cdb13 图片优化。升级不自动恢复历史 attention 任务。

## Review Focus

取消与恢复竞争、领取超时的迟到响应、另一商品执行中的核查、核查已提交但返回失败、跨用户批次访问，均在对应数据库或路由测试覆盖。

## 任务一：核查返回错误

- [x] `tests/test_scheduled_batch.py` 增加真实核查后 `_log_to_dict` 序列化测试，先观察 MissingGreenlet。
- [x] `common/services/publish_log_reconciliation.py` 显式刷新；`product_publish.py` 固定异常提示；验证两种核查及权限。

## 任务二：剩余队列继续及历史恢复

- [x] 修改 `tests/test_scheduled_batch.py` 复现未知项阻断，增加超时恢复、取消优先与只恢复 pending 测试。
- [x] `publish_batch_runner.py` 跳过未知项，继续 pending；`publish_batch_jobs.py` 新增受锁保护的 `resume(batch_id,user_id)`；真实接口仍只登记任务。
- [x] `product_publish.py`、`productPublish.ts` 和 `BatchTaskHistory.tsx` 增加手动恢复入口、确认和防重复提交。
- [x] 浏览器模拟恢复及失败；服务回归、前端构建、独立审查。记录结果，等待用户推送指令。

## 验证记录

2026-11-07：MySQL8 真实核查后序列化先复现 MissingGreenlet；修改后通过。双会话同时核查先复现旧快照使已全部核查的任务仍 attention，改为批次锁内当前读后通过。完整服务回归后台274、调度3、WebSocket6，共283项；Node53项；前端构建及5组浏览器流程通过（恢复入口、删除历史、清空日志、发布流程、店铺选择与昵称）。独立审查无剩余阻断问题。

Ruling: 本机 Docker Desktop 因已有 socket 启动错误不可用，测试改用独立临时容器、内部网络与空白 MySQL；只复用运行镜像作依赖，所有平台调用模拟，不连接生产数据库或执行真实发布。空白测试库按项目 DDL 初始化账号默认值及统一字符集后完整回归通过；不为测试环境差异修改产品代码。

本次代码保存在隔离分支，不推送、不部署，不自动恢复线上历史任务。
