#!/usr/bin/env swift
// TextEdit-parity: NSTextView uses the same text system as TextEdit.
// Simulates pull-to-mark + insertText replace (post-commit 1→1).
// Run: swift scripts/verify_post_commit_nstextview.swift

import AppKit
import Foundation

func replaceGrapheme(in tv: NSTextView, location: Int, old: String, new: String) -> String {
    let range = NSRange(location: location, length: (old as NSString).length)
    // Path A: pull committed into mark
    let attrs: [NSAttributedString.Key: Any] = [
        .backgroundColor: NSColor.selectedTextBackgroundColor,
        .underlineStyle: NSUnderlineStyle.single.rawValue,
    ]
    let marked = NSAttributedString(string: old, attributes: attrs)
    tv.setMarkedText(marked, selectedRange: NSRange(location: 0, length: 0), replacementRange: range)
    let mr = tv.markedRange()
    if mr.location != NSNotFound, mr.length > 0 {
        tv.insertText(new, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        return tv.string
    }
    // Path B: delete then insert
    tv.insertText("", replacementRange: range)
    tv.insertText(new, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    return tv.string
}

var fails = 0
func check(_ name: String, _ got: String, _ want: String) {
    let gl = (got as NSString).length
    let wl = (want as NSString).length
    if got == want, gl == wl {
        print("PASS \(name): \"\(got)\" len=\(gl)")
    } else {
        print("FAIL \(name): got \"\(got)\"(len=\(gl)) want \"\(want)\"(len=\(wl))")
        fails += 1
    }
}

// --- TextEdit storage simulation ---
let before = "我是學生"
let tv = NSTextView(frame: NSRect(x: 0, y: 0, width: 400, height: 200))
tv.string = before
print("BEFORE: \"\(before)\" len=\((before as NSString).length)")

// Replace 是 (index 1) → 視
let after1 = replaceGrapheme(in: tv, location: 1, old: "是", new: "視")
check("NSTextView 是→視", after1, "我視學生")
print("AFTER1: \"\(after1)\" len=\((after1 as NSString).length)")

// Continuous: replace 學 (index 2 in 我視學生) → 血
let after2 = replaceGrapheme(in: tv, location: 2, old: "學", new: "血")
check("NSTextView continuous 學→血", after2, "我視血生")
print("AFTER2: \"\(after2)\" len=\((after2 as NSString).length)")

// Third: 生→身
let after3 = replaceGrapheme(in: tv, location: 3, old: "生", new: "身")
check("NSTextView continuous 生→身", after3, "我視血身")
print("AFTER3: \"\(after3)\" len=\((after3 as NSString).length)")
check("net length still 4", "\((after3 as NSString).length)", "4")

if fails == 0 {
    print("ALL NSTEXTVIEW CHECKS PASSED (TextEdit text-system parity)")
    exit(0)
} else {
    print("FAILED \(fails)")
    exit(1)
}
