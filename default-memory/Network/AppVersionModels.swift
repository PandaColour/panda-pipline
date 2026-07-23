//
//  AppVersionModels.swift
//  aiphone
//
//  OpenAPI「版本返回对象」develop 混淆字段映射（明文可解码；密文需后续解密）。
//

import Foundation

/// `GET /api/common/appVersion` 解析后的业务模型（逻辑字段名）。
struct AppVersionInfo: Equatable {
    /// `0` 非最新；`1` 最新
    let isLatestAppVersion: Int
    let update: AppUpdateInfo?

    var needsUpdate: Bool { isLatestAppVersion == 0 }
    var isForceUpdate: Bool { update?.isForceUpdate == true }
}

struct AppUpdateInfo: Equatable {
    let appDesc: String?
    let appLogoUrl: String?
    let appResourceUrl: String?
    let appTitle: String?
    let appVersion: String?
    let isForceUpdate: Bool
}

/// develop 混淆名解码（OpenAPI 事实）。
private struct AppVersionDataDTO: Decodable {
    let isLatest: Int?
    let update: AppUpdateInfoDTO?

    enum CodingKeys: String, CodingKey {
        case isLatest = "dVLp8aYcBCUXCXsH3"
        case update = "vk9_shRD9YKqa"
        // 逻辑名兜底（Mock / 明文未混淆）
        case isLatestLogical = "isLatestAppVersion"
        case updateLogical = "updateInfoResp"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        isLatest = try c.decodeIfPresent(Int.self, forKey: .isLatest)
            ?? c.decodeIfPresent(Int.self, forKey: .isLatestLogical)
        update = try c.decodeIfPresent(AppUpdateInfoDTO.self, forKey: .update)
            ?? c.decodeIfPresent(AppUpdateInfoDTO.self, forKey: .updateLogical)
    }
}

private struct AppUpdateInfoDTO: Decodable {
    let appDesc: String?
    let appLogoUrl: String?
    let appResourceUrl: String?
    let appTitle: String?
    let appVersion: String?
    let isForceUpdate: Bool?

    enum CodingKeys: String, CodingKey {
        case appDesc = "xbeI308__Ue2TT0N"
        case appLogoUrl = "hUTNAO3gUjRpTpGIRn"
        case appResourceUrl = "cqRTPeyvZkI5"
        case appTitle = "pKSTYy9yVxy"
        case appVersion = "nG8DArXd3kW5QOs"
        case isForceUpdate = "nyGhv5Y9uuC8MR4"
        case appDescL = "appDesc"
        case appLogoUrlL = "appLogoUrl"
        case appResourceUrlL = "appResourceUrl"
        case appTitleL = "appTitle"
        case appVersionL = "appVersion"
        case isForceUpdateL = "isForceUpdate"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        appDesc = try c.decodeIfPresent(String.self, forKey: .appDesc)
            ?? c.decodeIfPresent(String.self, forKey: .appDescL)
        appLogoUrl = try c.decodeIfPresent(String.self, forKey: .appLogoUrl)
            ?? c.decodeIfPresent(String.self, forKey: .appLogoUrlL)
        appResourceUrl = try c.decodeIfPresent(String.self, forKey: .appResourceUrl)
            ?? c.decodeIfPresent(String.self, forKey: .appResourceUrlL)
        appTitle = try c.decodeIfPresent(String.self, forKey: .appTitle)
            ?? c.decodeIfPresent(String.self, forKey: .appTitleL)
        appVersion = try c.decodeIfPresent(String.self, forKey: .appVersion)
            ?? c.decodeIfPresent(String.self, forKey: .appVersionL)
        isForceUpdate = try c.decodeIfPresent(Bool.self, forKey: .isForceUpdate)
            ?? c.decodeIfPresent(Bool.self, forKey: .isForceUpdateL)
    }
}

enum AppVersionParser {
    /// 解析明文 `{code,data,msg}`；密文或非 JSON 返回 `encryptedResponseUnsupported` / `decodingFailed`。
    /// Network 层（R-002）成功解密后此处应已是明文。
    static func parse(data: Data) -> Result<AppVersionInfo, NetworkError> {
        if ResponseCrypto.looksEncrypted(data) {
            return .failure(.encryptedResponseUnsupported)
        }
        do {
            let envelope = try JSONDecoder().decode(APIEnvelope<AppVersionDataDTO>.self, from: data)
            guard envelope.code == 200, let payload = envelope.data else {
                return .failure(.business(code: envelope.code, message: envelope.msg ?? ""))
            }
            let info = AppVersionInfo(
                isLatestAppVersion: payload.isLatest ?? 1,
                update: payload.update.map {
                    AppUpdateInfo(
                        appDesc: $0.appDesc,
                        appLogoUrl: $0.appLogoUrl,
                        appResourceUrl: $0.appResourceUrl,
                        appTitle: $0.appTitle,
                        appVersion: $0.appVersion,
                        isForceUpdate: $0.isForceUpdate ?? false
                    )
                }
            )
            return .success(info)
        } catch {
            return .failure(.decodingFailed(underlying: error))
        }
    }

    #if DEBUG
    static func mock(isForce: Bool, isLatest: Int = 0) -> AppVersionInfo {
        AppVersionInfo(
            isLatestAppVersion: isLatest,
            update: AppUpdateInfo(
                appDesc: "Hay una nueva versión disponible. Actualiza para continuar.",
                appLogoUrl: nil,
                appResourceUrl: "https://apps.apple.com",
                appTitle: "Actualización Importante",
                appVersion: "9.9.9",
                isForceUpdate: isForce
            )
        )
    }
    #endif
}
