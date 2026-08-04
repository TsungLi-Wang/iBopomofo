// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// v2.10.0 Option B: post-commit clawback is retired.
// Soft-finalize keeps text marked; reselect uses the native reading grid.
// These stubs remain so any residual call sites compile.

import Cocoa
import InputMethodKit

extension McBopomofoInputMethodController {

    /// Always no-op (post-commit intercept removed).
    func tryHandlePostCommitReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        return false
    }

    func armPostCommitReselect() {
        postCommitReselectArmed = false
    }

    func disarmPostCommitReselect() {
        postCommitReselectArmed = false
    }
}
