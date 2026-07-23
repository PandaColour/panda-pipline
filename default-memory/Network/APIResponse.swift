//
//  APIResponse.swift
//  aiphone
//

import Foundation

/// 通用明文信封 `{code,data,msg}`
struct APIEnvelope<T: Decodable>: Decodable {
    let code: Int
    let data: T?
    let msg: String?
}

/// `confusionJson` 的 data 为下载 URL 字符串
typealias ConfusionJsonEnvelope = APIEnvelope<String>
