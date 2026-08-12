-- Opens ~/Library/Input Methods so the user can drag iBopomofo.app in.
tell application "Finder"
    set inputMethodsFolder to (path to home folder as text) & "Library:Input Methods:"
    open folder inputMethodsFolder
    activate
end tell