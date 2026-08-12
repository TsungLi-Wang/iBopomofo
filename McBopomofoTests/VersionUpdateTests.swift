// Copyright (c) 2022 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

import Testing

@testable import iBopomofo

@Suite("Version Update API Tests")
final class VersionUpdateApiTests {
    @Test("Version Update API Test")
    func testFetchVersionUpdateInfo() async  {
        // 本 fork 自動更新停用,Info.plist 未設定 UpdateInfoEndpoint。此時
        // `VersionUpdateApi.check` 會直接回傳 nil 而「不呼叫 callback」——若仍
        // 無條件 await callback,continuation 永不 resume,整包 `xcodebuild test`
        // 會卡死在這個測試。因此先判斷有沒有發出請求,沒有就視為通過。
        let result: Result<VersionUpdateApiResult, Error>? = await withCheckedContinuation { continuation in
            let task = VersionUpdateApi.check(forced: true) { result in
                continuation.resume(returning: result)
            }
            if task == nil {
                continuation.resume(returning: nil)
            }
        }

        switch result {
        case .none:
            // 未設定更新端點,沒有可檢查的版本資訊,屬預期狀況。
            break
        case let .failure(error):
            Issue.record(error)
        case .success:
            break
        }
    }
}
