# Android 工程资源

- **仅 Android 项目：** 简单 SVG 按项目工具链转换为 VectorDrawable，核对 viewport、逻辑 dp 尺寸和不支持的效果；复杂效果从原件按明确倍率栅格化，选择与像素尺寸/逻辑尺寸匹配的 drawable 密度目录。使用 drawable-nodpi 须明确由布局控制的宽高或纵横比与缩放策略，在目标 density 下核对实际显示大小；仅设一边并使用 Fit/Crop 时须检查固有像素尺寸是否导致图形缩小、拉伸或误裁；不得把任意 @2x 文件直接当默认 drawable，或把迁移到 nodpi 当成通用修复。启动图标按项目对应图标资源类型处理。
