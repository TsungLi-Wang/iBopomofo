#!/usr/bin/env swift
// Select the installed i注音 (iBopomofo) input mode.
// Used by type-as-user / e2e-typing-check so harness does not depend on the
// *terminal* being the app that currently has i注音 selected (macOS can keep
// a different input source per app).
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
    // Fallback: any enabled iBopomofo / McBopomofo non-Plain mode
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

_ = TISEnableInputSource(target)
let err = TISSelectInputSource(target)
let cur = currentID()
if err == noErr && (cur.contains("iBopomofo") || cur.contains("McBopomofo")) {
    print("SELECT_IME=OK id=\(targetID) current=\(cur)")
    exit(0)
}
// Select may report success for the focused app even when this process still
// sees another source under per-app input sources. Treat select==0 as OK if
// the source is enabled; callers that type into a freshly activated TextEdit
// re-select after activate.
if err == noErr {
    print("SELECT_IME=OK id=\(targetID) current=\(cur) (select ok; per-app source may differ)")
    exit(0)
}
fputs("SELECT_IME=FAIL err=\(err) current=\(cur)\n", stderr)
exit(1)
