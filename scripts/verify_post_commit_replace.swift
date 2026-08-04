#!/usr/bin/env swift
// Standalone simulation of post-commit 1→1 replace (mirrors PostCommitStringDocument logic).
// Run: swift scripts/verify_post_commit_replace.swift

import Foundation

final class Doc {
    var text: String
    var caret: Int
    var markLoc: Int = -1
    var markLen: Int = 0

    init(_ text: String, caret: Int) {
        self.text = text
        self.caret = caret
    }

    var markActive: Bool { markLoc >= 0 && markLen >= 0 }

    func setMarked(_ s: String, replace: NSRange?) {
        let ns = text as NSString
        if let r = replace, r.location >= 0, r.location + r.length <= ns.length {
            text = ns.substring(to: r.location) + s + ns.substring(from: r.location + r.length)
            markLoc = r.location
            markLen = (s as NSString).length
            caret = markLoc + markLen
            return
        }
        if s.isEmpty {
            if markActive {
                let n = text as NSString
                text = n.substring(to: markLoc) + n.substring(from: markLoc + markLen)
                caret = markLoc
                markLoc = -1
                markLen = 0
            }
            return
        }
        if markActive {
            let n = text as NSString
            text = n.substring(to: markLoc) + s + n.substring(from: markLoc + markLen)
            markLen = (s as NSString).length
            caret = markLoc + markLen
        }
    }

    func insert(_ s: String, replace: NSRange?) {
        let ns = text as NSString
        if replace == nil, markActive {
            text = ns.substring(to: markLoc) + s + ns.substring(from: markLoc + markLen)
            caret = markLoc + (s as NSString).length
            markLoc = -1
            markLen = 0
            return
        }
        if let r = replace, r.location >= 0 {
            text = ns.substring(to: r.location) + s + ns.substring(from: r.location + r.length)
            caret = r.location + (s as NSString).length
            markLoc = -1
            markLen = 0
            return
        }
        let n = text as NSString
        text = n.substring(to: caret) + s + n.substring(from: caret)
        caret += (s as NSString).length
    }
}

func replace(doc: Doc, range: NSRange, old: String, new: String) -> String {
    // Path A: pull to mark then insert
    doc.setMarked(old, replace: range)
    if doc.markActive {
        doc.insert(new, replace: nil)
        return doc.text
    }
    // Path B: delete then insert
    doc.insert("", replace: range)
    doc.insert(new, replace: nil)
    return doc.text
}

// --- TextEdit-parity scenarios ---
var fails = 0
func expect(_ name: String, _ got: String, _ want: String) {
    if got == want {
        print("PASS \(name): \"\(got)\" (len=\((got as NSString).length))")
    } else {
        print("FAIL \(name): got \"\(got)\" want \"\(want)\"")
        fails += 1
    }
}

// 1) 我是學生, replace 是→視 at index 1
do {
    let s = "我是學生"
    let d = Doc(s, caret: 1)
    let r = NSRange(location: 1, length: 1)
    let out = replace(doc: d, range: r, old: "是", new: "視")
    expect("single replace 是→視", out, "我視學生")
    expect("length unchanged", "\((out as NSString).length)", "\((s as NSString).length)")
}

// 2) continuous three replaces
do {
    var s = "在再在"
    // replace each 在 with 再 one by one using mark path
    for i in [0, 2] { // positions of 在 in "在再在" after first replace becomes "再再在" ...
    }
    // step by step:
    var d = Doc("在再在", caret: 0)
    _ = replace(doc: d, range: NSRange(location: 0, length: 1), old: "在", new: "再")
    expect("c1", d.text, "再再在")
    d = Doc(d.text, caret: 2)
    _ = replace(doc: d, range: NSRange(location: 2, length: 1), old: "在", new: "再")
    expect("c2 continuous", d.text, "再再再")
    expect("c2 length", "\((d.text as NSString).length)", "3")
}

// 3) replace must not double
do {
    let d = Doc("AB", caret: 0)
    // simulate bug path: insert without replace
    d.insert("X", replace: nil)
    let buggy = d.text
    expect("bug demo inserts", buggy, "XAB") // documents what we avoid
}

if fails == 0 {
    print("ALL LOGIC CHECKS PASSED")
    exit(0)
} else {
    print("FAILED \(fails)")
    exit(1)
}
