# 常见陷阱和注意事项

## 1. 勿用 CreditReqQueryOutput 直接判断授信状态

**陷阱**：`CreditReqQueryOutput` 仅有 `status` 字段，无 `applState`，不能直接用 `ApplStatusEnum` 判断。

**正确做法**：必须通过 `applQueryTargetFacade.queryApplByApplNoAddUser()` 获取 `ApplStatusEnum`。

```java
// ❌ 错误：直接用 creditResult.getStatus()
// ✅ 正确：通过 applQueryTargetFacade 获取 ApplStatusEnum
ApplQueryOutput applResult = applQueryTargetFacade.queryApplByApplNoAddUser(businessNo);
ApplStatusEnum applStatusEnum = applResult.getApplStatusEnum();
```

## 2. 勿在共用方法内部添加业务逻辑

**陷阱**：修改 `backfillLoanAgreement()` 等共用方法可能影响其他调用方。

**正确做法**：在调用处判断，不修改共用方法内部逻辑。

```java
// ❌ 错误：在 backfillLoanAgreement() 内部添加授信状态判断
// ✅ 正确：在 backfill() 调用前判断授信状态
if (applStatusEnum.isFinalState() && !applStatusEnum.isApproved()) {
    continue;  // 跳过不上传
}
backfillLoanAgreement(custNo, businessNo, agreementNo, results);
```

## 3. 勿在降级路径触发作废

**陷阱**：降级路径失败后，不应触发作废（status="04"），仅应记录日志。

**正确做法**：
- 降级路径失败 → `log.warn` + `continue`（不加入 results）
- 降级路径授信拒绝 → `log.info` + `continue`（不加入 results）

## 4. 勿忽略 null 检查

**陷阱**：`applQueryTargetFacade.queryApplByApplNoAddUser()` 可能返回 null。

**正确做法**：
```java
if (applResult == null) {
    log.warn("查询获客状态失败: custNo={}, businessNo={}", custNo, businessNo);
    continue;
}
```

## 5. 勿在非终态时使用 isApproved()

**陷阱**：`ApplStatusEnum.isApproved()` 在非终态时无意义。

**正确做法**：先判断 `isFinalState()`，再判断 `isApproved()`。

```java
if (applStatusEnum != null && applStatusEnum.isFinalState() && !applStatusEnum.isApproved()) {
    // 授信拒绝
}
```

## 6. 单元测试中 mock 方法返回值时注意参数匹配

**陷阱**：`when(contractQueryFacade.queryCreditReq(...)).thenReturn(...)` 需匹配实际调用的参数。

**正确做法**：使用 `anyString()` 或 `any()` 匹配任意参数。

```java
// ❌ 错误：硬编码参数不匹配
when(contractQueryFacade.queryCreditReq("C001", "B001")).thenReturn(creditOutput);
// ✅ 正确：使用 anyString() 匹配任意参数
when(contractQueryFacade.queryCreditReq(anyString(), anyString())).thenReturn(creditOutput);
```