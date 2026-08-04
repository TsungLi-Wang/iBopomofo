// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// v2.10.0+: post-commit clawback retired (Option B).
// Path β (v2.12+): reselect is only delete-and-recompose via ShadowReselect.
// These stubs stay so any residual call sites compile; they are permanent no-ops.

import Foundation

extension McBopomofoInputMethodController {

    /// Retired clawback path — always false. Use shadow reselect after hard commit.
    @discardableResult
    func tryHandlePostCommitReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        false
    }

    func armPostCommitReselect() {
        postCommitReselectArmed = false
    }

    func disarmPostCommitReselect() {
        postCommitReselectArmed = false
    }
}
