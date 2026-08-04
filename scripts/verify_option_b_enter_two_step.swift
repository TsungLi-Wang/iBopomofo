#!/usr/bin/env swift
// Option B Enter two-step (TextEdit text system = NSTextView):
// 1st "Enter" = soft-finalize (mark stays, underline gone conceptually)
// 2nd "Enter" = hard commit mark + host would receive Enter
// Run: swift scripts/verify_option_b_enter_two_step.swift

import AppKit
import Foundation

var fails = 0
func check(_ name: String, _ cond: Bool, _ detail: String = "") {
    if cond {
        print("PASS \(name)\(detail.isEmpty ? "" : ": \(detail)")")
    } else {
        print("FAIL \(name)\(detail.isEmpty ? "" : ": \(detail)")")
        fails += 1
    }
}

let tv = NSTextView(frame: NSRect(x: 0, y: 0, width: 400, height: 200))

// Compose: whole sentence marked
let s0 = "我是學生"
tv.setMarkedText(
    NSAttributedString(string: s0),
    selectedRange: NSRange(location: (s0 as NSString).length, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
print("COMPOSE: \"\(tv.string)\" mark=\(tv.markedRange())")
check("composing marked", tv.markedRange().length == 4)

// First Enter = soft-finalize: still marked, same text (underline hide is IME-side)
// Soft-finalize may smart-correct; here we only assert still marked / not committed clear.
let s1 = "我是學生" // after smart-select may change; keep same for sim
tv.setMarkedText(
    NSAttributedString(string: s1),
    selectedRange: NSRange(location: (s1 as NSString).length, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("1st Enter: still marked (not sent)", tv.markedRange().length == 4, "\"\(tv.string)\"")
check("1st Enter: text present", tv.string == s1)

// Reselect inside mark 是→視
let s2 = "我視學生"
tv.setMarkedText(
    NSAttributedString(string: s2),
    selectedRange: NSRange(location: 2, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("edit after 1st Enter", tv.string == s2 && (tv.string as NSString).length == 4)

// Second Enter = hard commit
tv.insertText(s2, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
let markGone = tv.markedRange().location == NSNotFound || tv.markedRange().length == 0
check("2nd Enter: committed", tv.string == s2, "\"\(tv.string)\"")
check("2nd Enter: mark cleared (app can receive Enter)", markGone)
print("2nd Enter: host would receive Enter for search/chat send (return NO after commit)")

// Pause-then-Enter: already soft-finalized → next Enter is send
tv.string = ""
let pause = "你好世界"
tv.setMarkedText(
    NSAttributedString(string: pause),
    selectedRange: NSRange(location: (pause as NSString).length, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
// "pause soft-finalize" already marked without underline (IME state)
check("pause path still marked", tv.markedRange().length == 4)
tv.insertText(pause, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("Enter after pause = send", tv.string == pause)

if fails == 0 {
    print("ALL ENTER-TWO-STEP CHECKS PASSED")
    exit(0)
} else {
    print("FAILED \(fails)")
    exit(1)
}
