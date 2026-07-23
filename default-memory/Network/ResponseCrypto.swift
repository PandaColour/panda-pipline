//
//  ResponseCrypto.swift
//  aiphone
//
//  网络响应密文识别与解密（R-002）。
//  对齐既有 looksEncrypted 启发式，以及后端 DecryptRequestBodyAdapter 去引号后再 AES。
//

import Foundation

enum ResponseCrypto {
    /// 与 `AuthResponseCrypto` / `AppVersionParser` 一致：首字节非 `{`/`[`/空白则视为密文。
    static func looksEncrypted(_ data: Data) -> Bool {
        guard let first = data.first else { return true }
        if first == UInt8(ascii: "{") || first == UInt8(ascii: "[") { return false }
        if first == UInt8(ascii: " ") || first == UInt8(ascii: "\n") || first == UInt8(ascii: "\t") {
            return false
        }
        return true
    }

    /// HTTP 2xx 成功体：密文则去引号后 `AESCrypto.decrypt`；明文原样透传。
    static func decryptIfNeeded(_ data: Data) -> Result<Data, NetworkError> {
        guard looksEncrypted(data) else {
            return .success(data)
        }

        guard let base64 = ciphertextBase64(fromResponseBody: data), !base64.isEmpty else {
            logFail(reason: "invalidCiphertextEncoding")
            return .failure(.responseDecryptionFailed(reason: "invalidCiphertextEncoding"))
        }

        switch AESCrypto.decrypt(ciphertextBase64: base64, key: AppConfig.aesKey) {
        case .success(let plaintext):
            guard let plainData = plaintext.data(using: .utf8) else {
                logFail(reason: "utf8EncodingFailed")
                return .failure(.responseDecryptionFailed(reason: "utf8EncodingFailed"))
            }
            logOK(byteCount: plainData.count)
            return .success(plainData)
        case .failure(let error):
            let reason = describe(error)
            logFail(reason: reason)
            return .failure(.responseDecryptionFailed(reason: reason))
        }
    }

    /// 去掉外层空白与首尾配对 JSON 字符串引号；再移除残留 `"`（Base64 字母表不含引号，对齐后端 `replaceAll("\"","")`）。
    static func ciphertextBase64(fromResponseBody data: Data) -> String? {
        guard var text = String(data: data, encoding: .utf8) else { return nil }
        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.count >= 2, text.hasPrefix("\""), text.hasSuffix("\"") {
            text = String(text.dropFirst().dropLast())
        }
        text = text.replacingOccurrences(of: "\"", with: "")
        return text.isEmpty ? nil : text
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

    private static func logOK(byteCount: Int) {
        #if DEBUG
        NSLog("[R-002] response decrypt ok bytes=%d", byteCount)
        NSLog(
            "[AES][R-004-crypto] real decrypt ok bytes=%d keyKind=%@",
            byteCount,
            CryptoMockPolicy.keyKindLabel
        )
        #endif
    }

    private static func logFail(reason: String) {
        #if DEBUG
        NSLog("[R-002] response decrypt fail reason=%@", reason)
        NSLog("[AES][R-004-crypto] real decrypt fail reason=%@", reason)
        #endif
    }
}
