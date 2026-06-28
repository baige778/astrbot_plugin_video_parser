# AstrBot 短视频解析插件

纯AI制作，个人使用平台只有抖和哔其他平台未测试，有需要的可以直接fork到自己仓库内修改。
自动解析短视频/图集分享链接，获取直链后在聊天中直接发送视频和图集。

## ✨ 功能

- 🎬 **视频直链解析** — 发送抖音、B站、快手等平台的分享链接，自动获取视频直链并发送
- 🖼️ **图集解析** — 支持图文/图集分享，一次解析多张图片
- 🔍 **智能平台识别** — 一条正则自动匹配 20+ 平台，无需手动选择
- 🃏 **小程序卡片支持** — 自动从 QQ 小程序消息卡片中提取链接
- 🖼️ **封面图提取** — 发送视频时可附带封面缩略图（可配置开关）
- ✏️ **自定义提示语** — 处理中提示文字可自定义，留空则不发送
- 📦 **视频大小限制** — 超过限制的视频不会发送，避免炸号

## 📋 支持的平台

| 平台 | 域名 |
|------|------|
| 抖音 | v.douyin.com, www.douyin.com |
| TikTok | vm.tiktok.com, www.tiktok.com |
| 快手 | v.kuaishou.com |
| B站 | bilibili.com, b23.tv |
| 小红书 | xhslink.com, www.xiaohongshu.com |
| 微博 | weibo.com, weibo.cn |
| 西瓜视频 | v.ixigua.com |
| 微视 | isee.weishi.qq.com |
| 皮皮虾 | h5.pipix.com |
| 火山小视频 | share.huoshan.com |
| 梨视频 | www.pearvideo.com |
| 好看视频 | xspshare.baidu.com |
| 虎牙 | v.huya.com |
| AcFun | www.acfun.cn |
| 美拍 | meipai.com |
| 逗拍 | doupai.cc |
| 全民 K 歌 | kg.qq.com |
| 6 间房 | 6.cn |

## ⚙️ 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `parser_api_base_url` | string | `http://127.0.0.1:17992` | 解析 API 服务地址 |
| `video_max_size_mb` | int | `50` | 视频最大大小（MB），超过则不发送 |
| `request_timeout_ms` | int | `15000` | API 请求超时（毫秒） |
| `send_cover` | bool | `true` | 是否发送视频封面图 |
| `processing_message` | string | `ikun解析bot正在处理中。。。` | 处理中提示文字，留空不发送 |

## 🚀 安装

1. 在 AstrBot 插件市场搜索 `astrbot_plugin_video_parser` 安装
2. 配置解析 API 地址（需自行部署视频解析后端）
3. 重启插件即可使用

## 🔧 依赖

- 视频解析 API 后端（需自行部署，插件通过 HTTP 调用）
- https://github.com/wujunwei928/parse-video-py（API部署项目）
- AstrBot v4.x+

## 📝 使用

在聊天中直接发送视频/图集分享链接即可：

```
https://v.douyin.com/xxxxx/
https://b23.tv/xxxxx
https://xhslink.com/xxxxx
```

也支持 QQ 小程序卡片形式的分享。

## 📄 许可证
菜得抠脚
