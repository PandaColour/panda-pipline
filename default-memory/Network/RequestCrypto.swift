//
//  RequestCrypto.swift
//  aiphone
//
//  网络请求 JSON body 加密（R-003）。
//  明文 JSON → AESCrypto.encrypt → Base64 UTF-8 直接作 httpBody（§3.2-A，无外层引号）。
//

import Foundation

enum RequestCrypto {
    /// 将逻辑字段字典序列化为明文 JSON，再 AES 加密为 §3.2-A 密文 body。
    /// 失败返回可区分 `requestEncryptionFailed`，调用方不得上送。
    static func encryptJSONBody(_ jsonBody: [String: Any]) -> Result<Data, NetworkError> {
        let plainData: Data
        do {
            plainData = try JSONSerialization.data(withJSONObject: jsonBody, options: [])
        } catch {
            return .failure(.decodingFailed(underlying: error))
        }

        guard let plaintext = String(data: plainData, encoding: .utf8) else {
            logFail(api: nil, reason: "utf8EncodingFailed")
            return .failure(.requestEncryptionFailed(reason: "utf8EncodingFailed"))
        }

        switch AESCrypto.encrypt(plaintext: plaintext, key: AppConfig.aesKey) {
        case .success(let base64):
            guard let body = base64.data(using: .utf8) else {
                logFail(api: nil, reason: "utf8EncodingFailed")
                return .failure(.requestEncryptionFailed(reason: "utf8EncodingFailed"))
            }
            return .success(body)
        case .failure(let error):
            let reason = describe(error)
            logFail(api: nil, reason: reason)
            return .failure(.requestEncryptionFailed(reason: reason))
        }
    }

    // MARK: - Observability

    static func logOK(api: String?, byteCount: Int) {
        #if DEBUG
        let keyKind = CryptoMockPolicy.keyKindLabel
        if let api {
            NSLog("[R-003] request encrypt ok api=%@ bytes=%d", api, byteCount)
            NSLog(
                "[AES][R-004-crypto] real encrypt ok api=%@ bytes=%d keyKind=%@",
                api,
                byteCount,
                keyKind
            )
        } else {
            NSLog("[R-003] request encrypt ok bytes=%d", byteCount)
            NSLog("[AES][R-004-crypto] real encrypt ok bytes=%d keyKind=%@", byteCount, keyKind)
        }
        #endif
    }

    static func logFail(api: String?, reason: String) {
        #if DEBUG
        if let api {
            NSLog("[R-003] request encrypt fail api=%@ reason=%@", api, reason)
            NSLog("[AES][R-004-crypto] real encrypt fail api=%@ reason=%@", api, reason)
        } else {
            NSLog("[R-003] request encrypt fail reason=%@", reason)
            NSLog("[AES][R-004-crypto] real encrypt fail reason=%@", reason)
        }
        #endif
    }

    // MARK: - Private

    private static func describe(_ error: AESCrypto.Error) -> String {
        switch error {
        case .emptyKey:
            return "emptyKey"
        case .invalidKeyLength(let length):
            return "invalidKeyLength(\(length))"
        case .utf8EncodingFailed:
            return "utf8EncodingFailed"
        case .invalidBase64:
            return "invalidBase64"
        case .cryptFailed(let status):
            return "cryptFailed(status:\(status))"
        }
    }
}
