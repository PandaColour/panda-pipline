# 代码规范

## 项目结构

```
cloudbank-* 项目（Java）
├── src/main/java/
│   ├── com/cloudbank/common/enums/     # 公共枚举
│   ├── com/cloudbank/ags/             # 协议/授信合同模块
│   │   ├── job/                       # 定时任务
│   │   ├── facade/                    # Facade 接口定义
│   │   │   └── dto/                   # DTO 对象
│   │   └── service/                   # 服务层
│   └── ...
└── src/test/java/                     # 单元测试
    └── com/cloudbank/ags/job/         # 测试用例与源码同包
```

## 命名规范

- Java 类名：大驼峰，如 `AuthFillJob`
- 方法名：小驼峰，如 `backfill()`
- 枚举常量：大写下划线，如 `APPROVED`、`REJECTED`
- 测试方法：`test场景_条件_预期结果()` 格式
- 常量：全大写下划线，如 `STATUS_UPLOAD_SUCCESS`

## 注释规范

- 类注释：说明功能、需求背景、关键约束
- 方法注释：说明【修改说明】、【重要】等标记
- 代码行注释：标记【关键修改】、【禁止修改】等

## 日志规范

- `log.info`：正常业务跳过（如授信拒绝跳过）
- `log.warn`：查询失败但不影响主流程
- `log.error`：降级查询失败等异常情况

## 关键约束

- **禁止修改共用方法内部逻辑**：如 `backfillLoanAgreement()` 为共用方法
- **入口方法无需改动**：如 `execute()` 为定时任务入口
- **外部依赖不改**：如 `CreditReqQueryOutput`、`ApplStatusEnum`
