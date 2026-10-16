"""
极验验证码配置

从环境变量读取配置，提供默认值
"""
import os


class GeetestConfig:
    """极验验证码配置类"""
    
    # 极验分配的captcha_id（从环境变量读取，有默认值）
    CAPTCHA_ID = os.getenv("GEETEST_CAPTCHA_ID", "a30cdbb466e9349385762477cb2c7df6")
    
    # 极验分配的私钥（从环境变量读取，有默认值）
    PRIVATE_KEY = os.getenv("GEETEST_PRIVATE_KEY", "6f70322308eb29ae0d85516a14a32d2c")
    
    # 用户标识（可选）
    USER_ID = os.getenv("GEETEST_USER_ID", "xianyu_system")
    
    # 客户端类型：web, h5, native, unknown
    CLIENT_TYPE = "web"
    
    # API地址（走 https：validate 请求里带签名参数，不该明文在公网上跑；
    # 且 443 端口比 80 更少被中间设备干扰）
    API_URL = "https://api.geetest.com"
    REGISTER_URL = "/register.php"
    VALIDATE_URL = "/validate.php"
    
    # SDK版本
    VERSION = "python-fastapi:3.1.1"
    
    # 请求超时时间（秒）。服务器在海外、极验节点在国内，3 秒偏紧，放宽到 5 秒
    TIMEOUT = 5.0
    
    # 网络抖动时的重试次数与间隔（秒）。
    # 极验节点偶发连不上（实测 2026-10-17 有一波持续 21 秒的 All connection attempts failed），
    # 重试能挡住几秒内的瞬时抖动；节点级故障挡不住，那种只能等它自愈
    RETRY_TIMES = 3
    RETRY_INTERVAL = 0.5
