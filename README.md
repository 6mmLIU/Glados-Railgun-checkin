# Railgun 自动签到

GLaDOS 网页签到每天北京时间 09:17 在 GitHub 托管的 Chrome 中运行，使用独立的 `GLADOS_BROWSER_SESSION` 仓库 Secret。工作流会核对官网签到响应和当天积分流水。会话需要重新登录时，请使用与云端 Chrome 匹配的会话更新该 Secret。

Railgun 的 GitHub Actions 计划每天北京时间 12:17 和 18:17 运行，签到失败会标记任务失败。

## 食用方式：

### 注册一个GLaDOS的账号([注册地址](https://glados.space/landing/0A58E-NV28S-6U3QV-33VMG))

#### 我的邀请码：([0A58E-NV28S-6U3QV-33VMG](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

### **Fork**本仓库

![图片加载失败](imgs/1.png)

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`GLADOS_COOKIES`，其值对应 Railgun 账号的 Cookie 值中的有效部分（获取方式如下）

- 在 Railgun 的积分页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- `GLADOS_COOKIES` 中的多个 Cookie 用 `&` 分隔。旧列表混合了两个网站的 Cookie 时，可以用仓库变量 `RAILGUN_COOKIE_INDEX` 指定 Railgun Cookie 的序号，序号从 1 开始。只保存一个 Railgun Cookie 时，把序号设为 1 或清除该变量。

3. 配置积分兑换策略（非必须）

- 添加1个`repository secret`，命名为`GLADOS_EXCHANGE_PLAN`，配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 |
|---|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 (默认) |

> 不配置时默认为 `plan500`，即积分达到 500 时自动兑换 100 天

4. Cookie 过期检查

- 脚本会自动解析 `koa:sess` 中的 `_expire` 字段，并在通知中显示 Cookie 到期时间。
- 默认提前 7 天提醒。可以添加1个`repository secret`，命名为`COOKIE_EXPIRE_WARN_DAYS`，例如填 `14` 表示提前 14 天提醒。

> Cookie 过期后脚本无法自动重新登录。请重新登录 Railgun，复制新的 Cookie 后更新 `GLADOS_COOKIES`。

5. PushDeer 手机推送（非必须）

- 添加1个`repository secret`，命名为`PUSHDEER_SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### **star**自己的仓库

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 更新日志

- **2026-01**: 重构代码，添加log输出方便定位，支持新版网址，支持配置积分兑换策略。
- **2026-04**: 优化代码逻辑，优化日志输出，支持[新版域名](https://railgun.info) ，在 GLADOS_COOKIES 中添加新版域名下的 cookies 即可使用。


## 问题排查与定位
- 大家可以通过查询 actions 中的 running checkin 日志快速定位问题，有其他问题提交issue。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份







