//
//  NetworkClient.swift
//  aiphone
//

import Foundation

final class NetworkClient {
    static let shared = NetworkClient()

    private let session: URLSession
    private let tokenStorage: TokenStorage

    init(session: URLSession = .shared, tokenStorage: TokenStorage = .shared) {
        self.session = session
        self.tokenStorage = tokenStorage
    }

    // MARK: - Public request

    func request(
        api: LogicalAPI,
        query: [String: String] = [:],
        jsonBody: [String: Any]? = nil,
        completion: @escaping (Result<Data, NetworkError>) -> Void
    ) {
        let endpoint = APIMapping.endpoint(for: api)
        var components = URLComponents()
        components.scheme = "https"
        components.host = AppConfig.developHost
        components.path = endpoint.obfuscatedPath

        if endpoint.method == .get, !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }

        guard let url = components.url else {
            completion(.failure(.invalidURL))
            return
        }

        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = endpoint.method.rawValue
        applyCommonHeaders(to: &request)

        if let jsonBody {
            // R-003：需加密 JSON body → 明文序列化 → AES → Base64 UTF-8（§3.2-A）；失败不上送。
            // multipart `upload` / 无 body GET / `download` 不走此路径。
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            switch RequestCrypto.encryptJSONBody(jsonBody) {
            case .success(let encryptedBody):
                request.httpBody = encryptedBody
                #if DEBUG
                RequestCrypto.logOK(api: endpoint.name, byteCount: encryptedBody.count)
                #endif
            case .failure(let error):
                #if DEBUG
                if case .requestEncryptionFailed(let reason) = error {
                    RequestCrypto.logFail(api: endpoint.name, reason: reason)
                }
                #endif
                completion(.failure(error))
                return
            }
        } else if endpoint.method == .get, !query.isEmpty {
            request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        }

        // 请求前检查 Token 续期钩子
        tokenStorage.checkAndTriggerRenewalIfNeeded()

        perform(request, decryptResponse: true, apiName: endpoint.name, completion: completion)
    }

    /// multipart 上传（可选 query，供 ocrVerification / checkFace）
    func upload(
        api: LogicalAPI,
        fileData: Data,
        fileName: String,
        mimeType: String,
        fieldName: String = FieldMapping.Body.uploadFile,
        query: [String: String] = [:],
        completion: @escaping (Result<Data, NetworkError>) -> Void
    ) {
        let endpoint = APIMapping.endpoint(for: api)
        var components = URLComponents()
        components.scheme = "https"
        components.host = AppConfig.developHost
        components.path = endpoint.obfuscatedPath
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }

        guard let url = components.url else {
            completion(.failure(.invalidURL))
            return
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url, timeoutInterval: 60)
        request.httpMethod = endpoint.method.rawValue
        applyCommonHeaders(to: &request)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        tokenStorage.checkAndTriggerRenewalIfNeeded()
        perform(request, decryptResponse: true, apiName: endpoint.name, completion: completion)
    }

    /// 远程文件下载（如 confusionJson 映射）；**不**做响应解密，避免误伤非 API 载荷。
    func download(url: URL, completion: @escaping (Result<Data, NetworkError>) -> Void) {
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = "GET"
        perform(request, decryptResponse: false, apiName: nil, completion: completion)
    }

    // MARK: - Headers

    private func applyCommonHeaders(to request: inout URLRequest) {
        request.setValue(AppConfig.acqChannel, forHTTPHeaderField: FieldMapping.Header.acqChannel)
        request.setValue(AppConfig.appVersionHeaderValue, forHTTPHeaderField: FieldMapping.Header.appVersion)
        request.setValue(AppConfig.appVersionStrHeaderValue, forHTTPHeaderField: FieldMapping.Header.appVersionStr)
        request.setValue(AppConfig.appsflyerId, forHTTPHeaderField: FieldMapping.Header.appsflyerId)
        request.setValue(AppConfig.clientType, forHTTPHeaderField: FieldMapping.Header.clientType)

        if let advId = AppConfig.advId, !advId.isEmpty {
            request.setValue(advId, forHTTPHeaderField: FieldMapping.Header.advId)
        }
        if let deviceId = AppConfig.deviceId, !deviceId.isEmpty {
            request.setValue(deviceId, forHTTPHeaderField: FieldMapping.Header.deviceId)
        }
        if let token = tokenStorage.token, !token.isEmpty {
            request.setValue(token, forHTTPHeaderField: FieldMapping.Header.token)
        }
    }

    // MARK: - Perform

    private func perform(
        _ request: URLRequest,
        decryptResponse: Bool,
        apiName: String?,
        completion: @escaping (Result<Data, NetworkError>) -> Void
    ) {
        let task = session.dataTask(with: request) { data, response, error in
            let finish: (Result<Data, NetworkError>) -> Void = { result in
                DispatchQueue.main.async { completion(result) }
            }

            if let error {
                let nsError = error as NSError
                if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorTimedOut {
                    finish(.failure(.timeout(underlying: error)))
                } else {
                    finish(.failure(.unreachable(underlying: error)))
                }
                return
            }

            guard let http = response as? HTTPURLResponse else {
                finish(.failure(.emptyResponse))
                return
            }

            guard (200..<300).contains(http.statusCode) else {
                finish(.failure(.httpStatus(code: http.statusCode, data: data)))
                return
            }

            guard let data, !data.isEmpty else {
                finish(.failure(.emptyResponse))
                return
            }

            guard decryptResponse else {
                finish(.success(data))
                return
            }

            switch ResponseCrypto.decryptIfNeeded(data) {
            case .success(let plain):
                #if DEBUG
                if let apiName, ResponseCrypto.looksEncrypted(data) {
                    NSLog("[R-002] response decrypt ok api=%@", apiName)
                    NSLog(
                        "[AES][R-004-crypto] real decrypt ok api=%@ keyKind=%@",
                        apiName,
                        CryptoMockPolicy.keyKindLabel
                    )
                } else if let apiName {
                    NSLog(
                        "[AES][R-004-crypto] plaintext bypass api=%@ bytes=%d",
                        apiName,
                        plain.count
                    )
                }
                #endif
                finish(.success(plain))
            case .failure(let networkError):
                #if DEBUG
                if let apiName {
                    NSLog(
                        "[R-002] response decrypt fail api=%@ error=%@",
                        apiName,
                        networkError.localizedDescription
                    )
                    NSLog(
                        "[AES][R-004-crypto] real decrypt fail api=%@ error=%@",
                        apiName,
                        networkError.localizedDescription
                    )
                }
                #endif
                finish(.failure(networkError))
            }
        }
        task.resume()
    }
}
