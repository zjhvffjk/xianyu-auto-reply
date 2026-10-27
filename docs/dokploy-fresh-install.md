# Dokploy 全新安装

本配置用于从空数据库开始使用 9001 维护版。不会迁移旧账号、订单、卡券、素材、模型配置或浏览器登录资料；本机 9001 的测试数据也不会上传。

## 部署文件

- 仓库：`zjhvffjk/xianyu-auto-reply`（原作者仓库的 Fork）
- Compose Path：`./docker-compose.dokploy.yml`
- 域名目标：`frontend` 服务的 `80` 端口。
- 数据库、缓存、上传文件、浏览器资料、日志和备份使用 `fresh_` 前缀的新命名卷。首次部署为空，后续更新继续沿用这些卷。
- 四个应用服务从对应 Dockerfile 构建，不依赖旧仓库应用镜像。
- 容器不使用固定全局名称，不发布宿主机端口；Dokploy 通过现有 `dokploy-network` 转发前端流量。
- 浏览器使用新版镜像支持的无头模式。三个 Python 服务都支持服务器已有的可选 `/etc/dokploy/outbound-proxy.env`，不复制该文件或其中凭据。

## 环境变量

将 `.env.dokploy.example` 中的变量填入 Dokploy 的 Environment。其中 `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`、`REDIS_PASSWORD`、`INTERNAL_API_TOKEN` 必须非空，使用各不相同的随机长值；未填写时配置检查会失败。

服务器上的代理地址或现有服务器设置可以继续保留，不需要提供到聊天或提交进 Git。首次部署后，修改数据库环境变量不会自动修改已经初始化的数据库用户密码。

## 操作顺序

1. 保持原服务不变，先核对新仓库、分支、Compose Path 和 Environment 均已选择正确。
2. 沿用原 Dokploy 服务时，保留其域名配置，目标仍为 `frontend:80`。更换 Compose 文件会改用新数据卷；旧卷不会被本配置删除。
3. 用户确认后执行部署，等待六个服务启动，检查登录、上传图片、账号登录、商品获取、卡券配置与定时发布。
4. 初始管理员沿用上游默认 `admin` / `admin123`；部署完成后立即通过个人设置修改密码，再添加闲鱼账号和模型配置。旧站的登录密码不会带入空库。
5. 新版验收后再处理旧仓库与旧数据卷。正常升级不需要点击 `Fresh Volumes`，也不需要清理数据库。

## 验证范围

Compose 已进行本机配置解析及部署结构检查。检查不代表已经在 VPS 成功构建或部署，也不代表已验证闲鱼平台上的实际发布或退款。
