//
//  CommonAPIService.swift
//  aiphone
//

import Foundation

final class CommonAPIService {
    static let shared = CommonAPIService()

    private let client: NetworkClient

    init(client: NetworkClient = .shared) {
        self.client = client
    }

    // MARK: - confusionJson（明文验收路径）

    /// 拉取明文 `{code,data,msg}`；`data` 为映射文件 URL。
    /// 可选尝试下载远程映射；失败则回退内置表并回调 `downloadError`。
    func fetchConfusionJson(
        applyRemoteMapping: Bool = true,
        completion: @escaping (Result<ConfusionJsonEnvelope, NetworkError>) -> Void
    ) {
        client.request(api: .confusionJson) { [weak self] result in
            switch result {
            case .failure(let error):
                completion(.failure(error))
            case .success(let data):
                do {
                    let envelope = try JSONDecoder().decode(ConfusionJsonEnvelope.self, from: data)
                    #if DEBUG
                    NSLog(
                        "[AES][R-004-crypto] confusionJson plaintext ok code=%d keyKind=%@",
                        envelope.code,
                        CryptoMockPolicy.keyKindLabel
                    )
                    #endif
                    guard applyRemoteMapping, let urlString = envelope.data, let url = URL(string: urlString) else {
                        completion(.success(envelope))
                        return
                    }
                    self?.client.download(url: url) { downloadResult in
                        switch downloadResult {
                        case .failure(let error):
                            ConfusionTable.clear()
                            NSLog("[CommonAPI] confusionJson download failed, fallback builtin: %@", error.localizedDescription)
                            completion(.success(envelope))
                        case .success(let fileData):
                            if fileData.isEmpty {
                                ConfusionTable.clear()
                                NSLog("[CommonAPI] confusionJson remote file empty, fallback builtin")
                                completion(.success(envelope))
                                return
                            }
                            do {
                                try ConfusionTable.apply(fromRemoteData: fileData)
                                NSLog(
                                    "[CommonAPI] confusionJson remote applied bytes=%d entries=%d",
                                    fileData.count,
                                    ConfusionTable.entryCount
                                )
                            } catch {
                                ConfusionTable.clear()
                                NSLog(
                                    "[CommonAPI] confusionJson remote parse failed, fallback builtin: %@",
                                    error.localizedDescription
                                )
                            }
                            completion(.success(envelope))
                        }
                    }
                } catch {
                    completion(.failure(.decodingFailed(underlying: error)))
                }
            }
        }
    }

    // MARK: - 其余通用 API（密文响应需后续解密；本项先通请求）

    func fetchAppVersion(completion: @escaping (Result<Data, NetworkError>) -> Void) {
        client.request(api: .appVersion, completion: completion)
    }

    /// 拉取并解析版本信息。Network 层会尝试解密密文；解密失败为 `responseDecryptionFailed`，Parser 仍见密文为 `encryptedResponseUnsupported`。
    func fetchAndParseAppVersion(completion: @escaping (Result<AppVersionInfo, NetworkError>) -> Void) {
        fetchAppVersion { result in
            switch result {
            case .failure(let error):
                #if DEBUG
                NSLog(
                    "[AES][R-004-crypto] appVersion fail category=%@ keyKind=%@",
                    error.category,
                    CryptoMockPolicy.keyKindLabel
                )
                #endif
                completion(.failure(error))
            case .success(let data):
                let parsed = AppVersionParser.parse(data: data)
                #if DEBUG
                switch parsed {
                case .success:
                    NSLog(
                        "[AES][R-004-crypto] appVersion parse ok keyKind=%@",
                        CryptoMockPolicy.keyKindLabel
                    )
                case .failure(let error):
                    NSLog(
                        "[AES][R-004-crypto] appVersion parse fail category=%@ keyKind=%@",
                        error.category,
                        CryptoMockPolicy.keyKindLabel
                    )
                }
                #endif
                completion(parsed)
            }
        }
    }

    func fetchSysConfig(key: String? = nil, completion: @escaping (Result<Data, NetworkError>) -> Void) {
        var query: [String: String] = [:]
        if let key {
            query[FieldMapping.Query.sysConfigKey] = key
        }
        client.request(api: .sysConfig, query: query, completion: completion)
    }

    func fetchDataDictInfo(type: String, completion: @escaping (Result<Data, NetworkError>) -> Void) {
        client.request(
            api: .dataDictInfo,
            query: [FieldMapping.Query.dataDictType: type],
            completion: completion
        )
    }

    func fetchProtocolConfig(completion: @escaping (Result<Data, NetworkError>) -> Void) {
        client.request(api: .protocolConfig, completion: completion)
    }

    func fetchProvincesCitiesArea(completion: @escaping (Result<Data, NetworkError>) -> Void) {
        client.request(api: .provincesCitiesArea, completion: completion)
    }

    func fetchTrackFilterRule(completion: @escaping (Result<Data, NetworkError>) -> Void) {
        client.request(api: .trackFilterRule, completion: completion)
    }

    func uploadFile(
        data: Data,
        fileName: String,
        mimeType: String,
        completion: @escaping (Result<Data, NetworkError>) -> Void
    ) {
        client.upload(
            api: .uploadFile,
            fileData: data,
            fileName: fileName,
            mimeType: mimeType,
            completion: completion
        )
    }
}
