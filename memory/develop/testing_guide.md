# 测试指南

## 单元测试规范

### 测试框架
- JUnit5 + Mockito Extension
- 使用 `@ExtendWith(MockitoExtension.class)` 启用 Mockito
- 使用 `@Mock` 注解模拟外部依赖

### 测试用例组织
```java
@ExtendWith(MockitoExtension.class)
class AuthFillJobTest {
    @Mock private ContractQueryFacade contractQueryFacade;
    @Mock private ApplQueryTargetFacade applQueryTargetFacade;
    @Mock private LoanAgreementService loanAgreementService;
    private AuthFillJob authFillJob;

    @BeforeEach
    void setUp() {
        authFillJob = new AuthFillJob(contractQueryFacade, applQueryTargetFacade, loanAgreementService);
    }
}
```

### 断言规范
- 使用 `assertEquals()` 验证返回值
- 使用 `assertTrue()/assertFalse()` 验证状态
- 使用 `assertThrows()` 验证异常
- 使用 `verify().never()` 验证方法未被调用

### 常见验证模式
```java
// 验证方法未被调用
verify(loanAgreementService, never()).uploadLoanAgreement(any(), any(), any());

// 验证结果列表为空
assertTrue(results.isEmpty());

// 验证结果列表不含特定状态
assertFalse(results.stream().anyMatch(r -> "04".equals(r.getStatus())));
```

## 测试覆盖率要求

- 核心业务逻辑：100% 覆盖
- 分支路径：主路径 + 降级路径均需覆盖
- 边界条件：null 返回、非终态等

## 测试用例命名
- 格式：`test场景_条件_预期结果`
- 示例：`testUc003a_FallbackPath_CreditRejected_DoesNotUploadOrInvalidate`
