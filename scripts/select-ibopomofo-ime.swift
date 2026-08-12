#!/usr/bin/env swift
// Select the installed i注音 (iBopomofo) input mode for the *currently focused* app.
//
// 2026-08-12 root cause (do not regress):
//   TISEnableInputSource on an already-enabled source can steal frontmost focus
//   to System Settings. Keys then land in TextEdit still on ABC → latin junk
//   like "su3cl3". Fix: only Enable when disabled; prefer Select alone.
//
// Used by type-as-user / e2e-typing-check. Exit 0 on success.
import Carbon
import Foundation

let preferredIDs = [
    "io.ibopomofo.inputmethod.iBopomofo.iBopomofo.Bopomofo",
    "org.openvanilla.inputmethod.McBopomofo.McBopomofo.Bopomofo",
]

func sourceID(_ src: TISInputSource) -> String? {
    guard let p = TISGetInputSourceProperty(src, kTISPropertyInputSourceID) else { return nil }
    return Unmanaged<CFString>.fromOpaque(p).takeUnretainedValue() as String
}

func isEnabled(_ src: TISInputSource) -> Bool {
    guard let p = TISGetInputSourceProperty(src, kTISPropertyInputSourceIsEnabled) else { return false }
    return CFBooleanGetValue(Unmanaged<CFBoolean>.fromOpaque(p).takeUnretainedValue())
}

func currentID() -> String {
    guard let cur = TISCopyCurrentKeyboardInputSource()?.takeRetainedValue(),
          let id = sourceID(cur) else { return "" }
    return id
}

let list = TISCreateInputSourceList(nil, true).takeRetainedValue() as! [TISInputSource]
var byID: [String: TISInputSource] = [:]
for src in list {
    if let id = sourceID(src) { byID[id] = src }
}

var target: TISInputSource?
var targetID = ""
for id in preferredIDs {
    if let src = byID[id] {
        target = src
        targetID = id
        break
    }
}
if target == nil {
    for (id, src) in byID {
        if id.contains("iBopomofo") && id.hasSuffix(".Bopomofo") && !id.contains("Plain") {
            target = src
            targetID = id
            break
        }
    }
}

guard let target else {
    fputs("SELECT_IME=FAIL(not found)\n", stderr)
    fputs("current=\(currentID())\n", stderr)
    exit(2)
}

// Only Enable when disabled. Re-Enable on an already-on source → System Settings
// steals frontmost (reproduced 2026-08-12); then TextEdit stays on ABC.
if !isEnabled(target) {
    let en = TISEnableInputSource(target)
    if en != noErr {
        fputs("SELECT_IME=FAIL enable=\(en) id=\(targetID)\n", stderr)
        exit(1)
    }
}

let err = TISSelectInputSource(target)
let cur = currentID()
if err != noErr {
    fputs("SELECT_IME=FAIL select=\(err) current=\(cur)\n", stderr)
    exit(1)
}

if cur.contains("iBopomofo") || cur.contains("McBopomofo") {
    print("SELECT_IME=OK id=\(targetID) current=\(cur)")
    exit(0)
}

// Per-app input sources: this process may still report ABC while the focused
// app received the selection. Callers that type into a just-activated TextEdit
// should re-check after activate; treat select==0 as soft OK.
print("SELECT_IME=OK id=\(targetID) current=\(cur) (select ok; per-app may differ)")
exit(0)
