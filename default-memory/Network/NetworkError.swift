//
//  NetworkError.swift
//  aiphone
//

import Foundation

enum NetworkError: Error, LocalizedError {
    case invalidURL
    case unreachable(underlying: Error)
    case timeout(underlying: Error)
    case httpStatus(code: Int, data: Data?)
    case emptyResponse
    case decodingFailed(underlying: Error)
    case business(code: Int, message: String)
    case mappingDownloadFailed(reason: String)
    /// 业务 Parser 仍见到密文（例如未走 Network 解密路径）；category=crypto。
    case encryptedResponseUnsupported
    /// Network 层识别为密文但解密失败（空密钥/非法 Base64/密文损坏等）；category=crypto。
    case responseDecryptionFailed(reason: String)
    /// JSON 请求体加密失败（空密钥/非法密钥长度/加密失败等）；category=crypto；不得上送。
    case requestEncryptionFailed(reason: String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .unreachable(let underlying):
            return "Network unreachable: \(underlying.localizedDescription)"
        case .timeout(let underlying):
            return "Request timeout: \(underlying.localizedDescription)"
        case .httpStatus(let code, _):
            return "HTTP status \(code)"
        case .emptyResponse:
            return "Empty response"
        case .decodingFailed(let underlying):
            return "Decoding failed: \(underlying.localizedDescription)"
        case .business(let code, let message):
            return "Business error \(code): \(message)"
        case .mappingDownloadFailed(let reason):
            return "Mapping download failed: \(reason)"
        case .encryptedResponseUnsupported:
            return "Encrypted response; not decrypted by network layer"
        case .responseDecryptionFailed(let reason):
            return "Response decryption failed: \(reason)"
        case .requestEncryptionFailed(let reason):
            return "Request encryption failed: \(reason)"
        }
    }

    /// 可区分错误类型，供上层展示
    var category: String {
        switch self {
        case .unreachable: return "unreachable"
        case .timeout: return "timeout"
        case .httpStatus: return "http"
        case .business: return "business"
        case .decodingFailed, .emptyResponse, .invalidURL: return "client"
        case .mappingDownloadFailed: return "mapping"
        case .encryptedResponseUnsupported, .responseDecryptionFailed, .requestEncryptionFailed:
            return "crypto"
        }
    }

    /// 密文相关失败（Network 解密失败，或 Parser 仍见密文）。DEBUG crypto Mock 门闩可复用，避免 R-002 后 Mock 失效。
    var isCryptoResponseIssue: Bool {
        switch self {
        case .encryptedResponseUnsupported, .responseDecryptionFailed:
            return true
        default:
            return false
        }
    }
}
