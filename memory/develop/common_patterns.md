# 常见代码模式

## 1. 降级路径模式（Fallback Pattern）

在核心服务调用失败时，降级到备用服务查询。

```java
try {
    // 主路径：核心服务查询
    CreditReqQueryOutput creditResult = contractQueryFacade.queryCreditReq(custNo, businessNo);
    if (creditResult != null) {
        // 主路径处理逻辑
    }
} catch (Exception e) {
    log.warn("核心查询异常，降级处理: custNo={}, error={}", custNo, e.getMessage());
    try {
        // 降级路径：备用服务查询
        ApplQueryOutput applResult = applQueryTargetFacade.queryApplByApplNoAddUser(businessNo);
        if (applResult != null) {
            // 降级路径处理逻辑
        }
    } catch (Exception fallbackEx) {
        log.error("降级查询失败: custNo={}", custNo, fallbackEx);
    }
}
```

**关键点**：
- 主路径失败不等于业务失败，需降级尝试
- 降级路径也需 try-catch 包裹，防止二次异常
- 降级失败时仅记录日志，不影响其他记录处理

## 2. 状态判断模式（State Check Pattern）

使用枚举的终态判断来决定业务行为。

```java
ApplStatusEnum applStatusEnum = applResult.getApplStatusEnum();
if (applStatusEnum != null && applStatusEnum.isFinalState() && !applStatusEnum.isApproved()) {
    // 授信拒绝：不处理，仅记录日志
    log.info("授信合同上传跳过-授信拒绝: custNo={}, businessNo={}, applState={}",
            custNo, businessNo, applState);
    continue;
}
// 授信通过或其他情况：继续原有逻辑
backfillLoanAgreement(custNo, businessNo, agreementNo, results);
```

**关键点**：
- 先判断 `isFinalState()`，非终态时 `isApproved()` 无意义
- 终态拒绝时使用 `continue` 跳过，不改变状态（防重处理）
- 日志需包含所有关键字段（custNo、businessNo、agreementNo、applState）

## 3. 防重处理模式（Idempotent Skip Pattern）

接受重复查询，通过状态判断避免重复处理。

```java
// 不改变状态、不标记 remark
if (isFinalStateAndRejected()) {
    log.info("授信合同跳过-授信拒绝: custNo={}, businessNo={}", custNo, businessNo);
    continue;  // 下次定时任务会重复拾取
}
```

**适用场景**：
- 定时任务处理
- 消息队列消费
- 批量数据处理
