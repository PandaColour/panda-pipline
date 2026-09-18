# Figma 资源筛选

本节统一限定本文所有“全部物料”“完整性”“远程资产集合”和资源访问阻塞的作用域：当前需求明确交付的页面、组件及交互状态。文件中的其他设计稿、草稿和未使用变体不因共享 Figma 链接而自动进入需求；不得缩减原始 AC。先建立范围与节点映射，再发现候选、判定用途、去重、获取必需资源，最后审计。结构读取完成不等于资源准备完成。

- `imageAssets` 是候选引用集合，不是下载清单；禁止下载整个文件的图片列表。仅检查当前范围内节点及其实际依赖。隐藏图层不能一律排除：需检查其是否在目标弹窗、加载态、交互或组件变体中使用。
- `exportSettings`（标记导出）仅是辅助线索，可能多标或漏标；是否下载以当前 UI AC、实际消费节点/状态和资源类型证据为准，不能以标记数量判断完整性。Ready for dev 是设计交付状态，Publish library 是组件/样式/变量发布，均不是图片下载白名单。已标记但范围外的资源不下载；未标记但被目标节点实际引用的图片、矢量或媒体必须核实并保留。
- 判定必须关联当前 UI AC、FRAME/状态、消费节点、图片填充 `imageRef`、组件引用或独立矢量边界及证据。先检查原生布局/纯色/渐变与媒体类型，禁止凭截图中的颜色认定可用 CSS/Compose 自绘。GIF、视频、Lottie 或原型动效不能因 PNG 预览看似静态而被替换；疑似动效未核实属于未决项。
- 按 file key + imageRef/资源节点 + 版本 + 导出设置去重，复用已验证缓存；同一原图的不同裁切记录消费节点的裁切参数，不重复下载原图。合成导出的父资源已覆盖子路径时，记录覆盖关系，不逐个导出内部矢量碎片。跨小需求可复用已验证文件复制到当前目录，禁止修改其他小需求；本地映射保持当前目录内可审计。
- 原始静态物料采用设计师导出设置；未设置时矢量优先 SVG、位图默认 PNG @2x，并记录实际倍率与画布。该默认值仅用于原件获取，最终入包格式、尺寸和倍率按当前项目平台的资源转换交接执行。动图/视频保留原格式和播放行为，另存静态参考图；不得统一转成 PNG。原型动画需记录触发、时序和实现约束，不得虚构可下载的动画文件。
- `asset_manifest.json` 新建或补充物料时使用 `schema_version: 3`，保留既有 requirement_id、figma_file_key、frames、remote_read、reference_screen 字段。每个候选资产保留 node_id、discovery、kind、usage，并增加布尔 `required` 和非空 `selection_evidence`（AC/消费节点/状态/引用或排除依据）；discovery 使用 imageAssets、imageRef、export-tagged、nested-custom-asset 或 font。无需遍历登记整个文件的无关图片，只登记范围内发现的候选与已检查后排除的候选。
- `decision: export|reuse` 仅用于 required=true，必须有 format、local_path 和物料映射；reuse 同样验证本地文件。排除使用 required=false、decision=skip、非空 skip_reason 和 selection_evidence；合法理由包括范围外、目标状态未使用、原生样式、父资源已覆盖，不能用“没标记导出”“有近似系统图标”或“下载失败”排除实际需要的资源。重复必需资源使用 reuse 并映射到同一已验证本地文件。动图/视频 kind 使用 animation/video，记录 animation_evidence（原始媒体与实际播放检查证据）；证据不足标记 decision=pending 并说明缺失，审计不得通过。
- 完整性按“目标范围内必需资源均有可用文件或合法复用”验收，不能按 imageAssets 总数或文件数量验收。评审独立核实 selection_evidence，不能仅信任 required=false 声明。已排除资源无需下载，也不触发资源访问阻塞；必需资源缺失或类型未决才影响对应 UI AC，报告列出具体节点与影响。
