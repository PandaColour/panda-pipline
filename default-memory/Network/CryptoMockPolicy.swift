//
//  CryptoMockPolicy.swift
//  aiphone
//
//  R-004：DEBUG crypto 自动 Mock 收敛策略。
//  Layer A（网络密文证明）可通过 `-R004RequireRealCrypto` 或 develop 真密钥关闭自动降级；
//  Layer B（显式 `-R0xx*Mock`）不受本策略删除。Release 恒不允许 crypto Mock。
//

import Foundation

enum CryptoMockPolicy {
    /// R-001 样例向量密钥（非 develop / 生产）。禁止冒充联调通过。
    static let sampleAESKey = "001580c2-f258-48fe-9c16-cf4f02fb"

    #if DEBUG
    /// 启动参数：强制 P0 真实加解密路径，关闭各模块 `allowCryptoMock`。
    static var requireRealCrypto: Bool {
        ProcessInfo.processInfo.arguments.contains("-R004RequireRealCrypto")
    }

    /// 当前密钥是否为样例（DEBUG 冒烟用）。
    static var isSampleAESKey: Bool {
        AppConfig.aesKey == sampleAESKey
    }

    /// 非空且非样例 → 视为已配置 develop/业务密钥（真值来源仍待同事/Apollo）。
    static var isDevelopAESKeyConfigured: Bool {
        !AppConfig.aesKey.isEmpty && !isSampleAESKey
    }

    /// DEBUG 下 `allowCryptoMock` 默认值：RequireRealCrypto 或已配真密钥时关闭自动降级。
    static var allowCryptoMockDefault: Bool {
        if requireRealCrypto { return false }
        if isDevelopAESKeyConfigured { return false }
        return true
    }

    static var keyKindLabel: String {
        if AppConfig.aesKey.isEmpty { return "empty" }
        if isSampleAESKey { return "sample" }
        return "develop"
    }

    /// 冷启应用到各 `*APIService`（须在样例密钥注入策略确定之后调用）。
    static func applyAllowCryptoMockToServices() {
        let allowed = allowCryptoMockDefault
        AuthAPIService.shared.allowCryptoMock = allowed
        HomeAPIService.shared.allowCryptoMock = allowed
        LoanMallAPIService.shared.allowCryptoMock = allowed
        BillsAPIService.shared.allowCryptoMock = allowed
        RepayAPIService.shared.allowCryptoMock = allowed
        ApplyConfirmAPIService.shared.allowCryptoMock = allowed
        QuotaAPIService.shared.allowCryptoMock = allowed
        CustomerServiceAPIService.shared.allowCryptoMock = allowed
        AcquisitionAPIService.shared.allowCryptoMock = allowed
        NSLog(
            "[R-004-crypto] apply allowCryptoMock=%@ requireRealCrypto=%@ keyKind=%@",
            allowed ? "YES" : "NO",
            requireRealCrypto ? "YES" : "NO",
            keyKindLabel
        )
    }

    static func logColdLaunchState() {
        NSLog(
            "[R-004-crypto] cold launch requireRealCrypto=%@ allowCryptoMockDefault=%@ keyKind=%@",
            requireRealCrypto ? "YES" : "NO",
            allowCryptoMockDefault ? "YES" : "NO",
            keyKindLabel
        )
    }
    #else
    static var requireRealCrypto: Bool { false }
    static var isSampleAESKey: Bool { false }
    static var isDevelopAESKeyConfigured: Bool {
        !AppConfig.aesKey.isEmpty
    }
    static var allowCryptoMockDefault: Bool { false }
    static var keyKindLabel: String {
        AppConfig.aesKey.isEmpty ? "empty" : "develop"
    }

    static func applyAllowCryptoMockToServices() {}
    static func logColdLaunchState() {}
    #endif
}
