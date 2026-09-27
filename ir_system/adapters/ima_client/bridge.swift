// Fixed, local accessibility bridge for the official IMA macOS app.
// No cookies, private APIs, arbitrary scripts or outbound model calls.
import Cocoa
import ApplicationServices

struct Stop: Error { let code: String }
func fail(_ code: String) throws -> Never { throw Stop(code: code) }
func attr(_ e: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?; return AXUIElementCopyAttributeValue(e, name as CFString, &value) == .success ? value : nil
}
func text(_ e: AXUIElement, _ name: String) -> String { attr(e,name) as? String ?? "" }
func children(_ e: AXUIElement) -> [AXUIElement] { attr(e,kAXChildrenAttribute) as? [AXUIElement] ?? [] }
func walk(_ e: AXUIElement, _ depth: Int = 0) -> [AXUIElement] {
    if depth > 28 { return [] }; var out=[e]
    for c in children(e) { out += walk(c,depth+1); if out.count > 12000 { break } }; return out
}
func label(_ e: AXUIElement) -> String {
    for key in [kAXTitleAttribute,kAXValueAttribute,kAXDescriptionAttribute] {
        let v=text(e,key); if !v.isEmpty { return v }
    }; return ""
}
func rect(_ e: AXUIElement) -> CGRect? {
    guard let a=attr(e,kAXPositionAttribute),let b=attr(e,kAXSizeAttribute),CFGetTypeID(a)==AXValueGetTypeID(),CFGetTypeID(b)==AXValueGetTypeID() else { return nil }
    var p=CGPoint.zero,s=CGSize.zero
    AXValueGetValue(unsafeBitCast(a,to:AXValue.self),.cgPoint,&p);AXValueGetValue(unsafeBitCast(b,to:AXValue.self),.cgSize,&s)
    return CGRect(origin:p,size:s)
}
func url(_ e: AXUIElement) -> URL? {
    if let u=attr(e,kAXURLAttribute) as? URL { return u }; return URL(string:text(e,kAXURLAttribute))
}
func query(_ u: URL?, _ key: String) -> String? { u.flatMap { URLComponents(url:$0,resolvingAgainstBaseURL:false)?.queryItems?.first(where:{$0.name==key})?.value } }
func mediaID(_ e: AXUIElement) -> String? {
    let u=url(e); let origin=query(u,"originUrl").flatMap(URL.init(string:))
    let id=query(origin,"media_id") ?? query(u,"media_id")
    return id?.range(of:"^[A-Za-z0-9_+=.-]{1,512}$",options:.regularExpression) != nil ? id : nil
}
func rowDate(_ e: AXUIElement) -> String? {
    var parent=e
    for _ in 0..<3 {
        guard let p=attr(parent,kAXParentAttribute) else {return nil};parent=unsafeBitCast(p,to:AXUIElement.self)
        let texts=walk(parent).filter{text($0,kAXRoleAttribute)=="AXStaticText"}.map{label($0)}
        // Never climb into the list and accidentally use a different row's date.
        if Set(texts.filter{$0.range(of:"\\.(pdf|docx?|pptx?|xlsx?|txt|md|csv|mp3|m4a|wav|mp4|zip|rar)$",options:[.regularExpression,.caseInsensitive]) != nil}).count > 1 {return nil}
        if let date=texts.first(where:{$0.range(of:"^(PDF|WORD|PPT|EXCEL|TXT|MARKDOWN|笔记)?\\s*([0-9]{1,4}/[0-9]{1,2}(/[0-9]{1,2})?|[0-9]{1,2}:[0-9]{2}|今天|昨天)(更新)?$",options:.regularExpression) != nil}) {return date}
    }
    return nil
}
func click(_ e: AXUIElement) throws {
    guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "com.tencent.imamac" else { try fail("ima_client_focus_changed") }
    if AXUIElementPerformAction(e,kAXPressAction as CFString) == .success { return }
    if let window=attr(e,kAXWindowAttribute) {
        AXUIElementPerformAction(unsafeBitCast(window,to:AXUIElement.self),kAXRaiseAction as CFString)
        Thread.sleep(forTimeInterval:0.2)
    }
    guard let r=rect(e),r.width>0,r.height>0 else { try fail("ima_client_control_unavailable") }
    let p=CGPoint(x:r.midX,y:r.midY)
    CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:p,mouseButton:.left)?.post(tap:.cghidEventTap)
    CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:p,mouseButton:.left)?.post(tap:.cghidEventTap)
}
func key(_ code: CGKeyCode, _ flags: CGEventFlags = []) throws {
    guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == "com.tencent.imamac" else { try fail("ima_client_focus_changed") }
    for down in [true,false] { let e=CGEvent(keyboardEventSource:nil,virtualKey:code,keyDown:down); e?.flags=flags;e?.post(tap:.cghidEventTap) }
}
func waitFor<T>(_ seconds: Double = 15, _ body: () -> T?) throws -> T {
    let end=Date().addingTimeInterval(seconds)
    repeat { if let value=body() { return value }; Thread.sleep(forTimeInterval:0.15) } while Date()<end
    try fail("ima_client_ui_timeout")
}
let fm=FileManager.default
func main(_ input: [String:Any]) throws -> [String:Any] {
    let command=input["command"] as? String ?? ""
    if command=="authorize" {
        let options=[kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String:true] as CFDictionary
        return ["status":AXIsProcessTrustedWithOptions(options) ? "ready":"needs_attention","code":"ima_accessibility_required"]
    }
    if !AXIsProcessTrusted() { try fail("ima_accessibility_required") }
    guard let running=NSRunningApplication.runningApplications(withBundleIdentifier:"com.tencent.imamac").first else { try fail("ima_client_not_running") }
    let app=AXUIElementCreateApplication(running.processIdentifier)
    AXUIElementSetMessagingTimeout(app,3)
    func windows() -> [AXUIElement] { attr(app,kAXWindowsAttribute) as? [AXUIElement] ?? [] }
    func all() -> [AXUIElement] { windows().flatMap { walk($0) } }
    func libraryArea() -> AXUIElement? { all().first { query(url($0),"knowledgeBaseId") != nil && text($0,kAXRoleAttribute)=="AXWebArea" } }
    if command=="check" { return ["status":"ready","platform":"macos","clientRunning":true] }
    if command=="inspect" {
        // Structural evidence only. Never return document content or signed URLs.
        let match=input["name"] as? String ?? ""
        return ["status":"ok","matches":all().filter{ !match.isEmpty && label($0)==match }.map{["role":text($0,kAXRoleAttribute),"rect":rect($0).map{NSStringFromRect($0)} ?? ""]},"windows":windows().map { ["title":text($0,kAXTitleAttribute),"roles":Array(Set(walk($0).map {text($0,kAXRoleAttribute)})).sorted()] },"library":libraryArea().flatMap{query(url($0),"knowledgeBaseId")} ?? ""]
    }
    guard ["open_library","list","scroll","open_file","download","close_document"].contains(command) else { try fail("ima_client_invalid_command") }
    if command=="open_library" {
        guard let name=input["name"] as? String,!name.isEmpty,name.count<=2000 else { try fail("ima_client_invalid_scope") }
        guard let area=libraryArea() else { try fail("ima_client_library_window_required") }
        if let expected=input["libraryId"] as? String,query(url(area),"knowledgeBaseId")==expected,text(area,kAXTitleAttribute)==name {
            return ["status":"ok","libraryId":expected,"name":name,"reusedView":true]
        }
        let candidates=walk(area).filter { text($0,kAXRoleAttribute)=="AXStaticText" && label($0)==name }
        let left=candidates.compactMap{rect($0)?.minX}.min()
        let matches=candidates.filter{rect($0)?.minX==left}
        guard matches.count==1 else { try fail("ima_client_library_ambiguous") }
        running.activate(options:[.activateIgnoringOtherApps])
        if let window=windows().first(where:{walk($0).contains(where:{CFEqual($0,area)})}) { AXUIElementPerformAction(window,kAXRaiseAction as CFString) }
        try click(matches[0])
        let updated: AXUIElement = try waitFor { guard let a=libraryArea(),text(a,kAXTitleAttribute)==name || walk(a).contains(where:{label($0)==name+" "+name}) else {return nil};return a }
        return ["status":"ok","libraryId":query(url(updated),"knowledgeBaseId") ?? "","name":name]
    }
    if command=="list" || command=="scroll" || command=="open_file" {
        guard let area=libraryArea(),let expected=input["libraryId"] as? String,query(url(area),"knowledgeBaseId")==expected else { try fail("ima_client_scope_changed") }
        var nodes=walk(area)
        if command=="list" {
            // Navigation can update the library header before its async content.
            nodes = try waitFor(20) {
                guard let fresh=libraryArea(),query(url(fresh),"knowledgeBaseId")==expected else {return nil}
                let current=walk(fresh)
                return current.contains{label($0).range(of:"^内容\\s*([（(][0-9,]+[）)]|[0-9,]+)$",options:.regularExpression) != nil} ? current:nil
            }
        }
        // A filename in a tooltip/chat message is not a directory row. Only
        // its immediate row's date may identify a file; never borrow a neighbour's.
        let fileTexts=nodes.filter {
            guard text($0,kAXRoleAttribute)=="AXStaticText",rect($0) != nil,let date=rowDate($0),label($0) != date else {return false}
            return label($0).range(of:"\\.(pdf|docx?|pptx?|xlsx?|txt|md|csv|mp3|m4a|wav|mp4|zip|rar)$",options:[.regularExpression,.caseInsensitive]) != nil || date.hasPrefix("笔记")
        }
        if command=="list" {
            let rows=fileTexts.map { e -> [String:Any] in
                return ["title":label(e),"displayDate":rowDate(e) ?? ""]
            }
            let total=nodes.map{label($0)}.first(where:{$0.range(of:"^内容\\s*([（(][0-9,]+[）)]|[0-9,]+)$",options:.regularExpression) != nil}) ?? ""
            return ["status":"ok","items":rows,"totalLabel":total,"libraryId":expected]
        }
        if command=="open_file" {
            guard let title=input["title"] as? String else { try fail("ima_client_invalid_scope") }
            let matches=fileTexts.filter{label($0)==title};guard matches.count==1 else {try fail("ima_client_file_ambiguous")}
            let existingIDs=Set(all().compactMap{mediaID($0)})
            running.activate(options:[.activateIgnoringOtherApps]);Thread.sleep(forTimeInterval:0.2)
            // Always open the selected row. A pre-existing document with the
            // same title could belong to a different library.
            try click(matches[0])
            let document: AXUIElement=try waitFor(25) {
                guard let focused=attr(app,kAXFocusedWindowAttribute) else {return nil}
                let current=walk(unsafeBitCast(focused,to:AXUIElement.self))
                return current.first {
                    guard text($0,kAXRoleAttribute)=="AXWebArea",mediaID($0) != nil else {return false}
                    let actual=text($0,kAXTitleAttribute)
                    if actual==title {return true}
                    if let cut=title.range(of:"…|\\.{3,}",options:.regularExpression) {
                        let prefix=String(title[..<cut.lowerBound]);return prefix.count>=12 && actual.hasPrefix(prefix) && (actual as NSString).pathExtension==(title as NSString).pathExtension
                    }
                    return false
                }
            }
            return ["status":"ok","mediaId":mediaID(document)!,"title":text(document,kAXTitleAttribute),"closeAfter":!existingIDs.contains(mediaID(document)!),"downloadAvailable":walk(document).contains{label($0)=="下载"}]
        }
        guard let last=fileTexts.last,let r=rect(last) else {
            if command=="scroll" && input["direction"] as? String == "top" { return ["status":"ok"] }
            try fail("ima_client_scroll_unavailable")
        }
        running.activate(options:[.activateIgnoringOtherApps])
        if let window=windows().first(where:{walk($0).contains(where:{CFEqual($0,area)})}) { AXUIElementPerformAction(window,kAXRaiseAction as CFString);Thread.sleep(forTimeInterval:0.1) }
        let e=CGEvent(scrollWheelEvent2Source:nil,units:.pixel,wheelCount:1,wheel1:input["direction"] as? String == "top" ? 100000 : -550,wheel2:0,wheel3:0)
        e?.location=CGPoint(x:r.midX,y:min(r.midY,(rect(area)?.maxY ?? r.maxY)-80));e?.post(tap:.cghidEventTap)
        Thread.sleep(forTimeInterval:0.4)
        return ["status":"ok"]
    }
    guard let id=input["mediaId"] as? String,let doc=all().first(where:{text($0,kAXRoleAttribute)=="AXWebArea" && mediaID($0)==id}) else { try fail("ima_client_document_changed") }
    if command=="close_document" {
        running.activate(options:[.activateIgnoringOtherApps]);Thread.sleep(forTimeInterval:0.2)
        guard let window=windows().first(where:{walk($0).contains(where:{CFEqual($0,doc)})}) else {try fail("ima_client_control_unavailable")}
        let tabs=walk(window).filter{text($0,kAXDescriptionAttribute)==text(doc,kAXTitleAttribute)}
        if let close=tabs.flatMap{children($0)}.first(where:{label($0)=="Close" || label($0)=="关闭"}) { try click(close) }
        // Never close a whole user window with potentially unrelated tabs.
        return ["status":"ok"]
    }
    guard let destination=input["destination"] as? String,destination.hasPrefix("/"),!fm.fileExists(atPath:destination),fm.fileExists(atPath:(destination as NSString).deletingLastPathComponent) else { try fail("ima_client_invalid_destination") }
    let buttons=walk(doc).filter{label($0)=="下载"};guard let button=buttons.first else {try fail("ima_client_download_unavailable")}
    running.activate(options:[.activateIgnoringOtherApps])
    if let window=windows().first(where:{walk($0).contains(where:{CFEqual($0,doc)})}) { AXUIElementPerformAction(window,kAXRaiseAction as CFString);Thread.sleep(forTimeInterval:0.2) }
    try click(button)
    // macOS exposes expanded Save as a sheet and compact Save as a dialog.
    let nameField: AXUIElement=try waitFor { all().first{ text($0,kAXIdentifierAttribute)=="saveAsNameTextField" } }
    let filename=(destination as NSString).lastPathComponent
    AXUIElementSetAttributeValue(nameField,kAXValueAttribute as CFString,filename as CFString)
    try key(5,[.maskCommand,.maskShift]) // official Save dialog: Go to Folder
    let folderField: AXUIElement=try waitFor { all().first{ text($0,kAXIdentifierAttribute)=="PathTextField" || text($0,kAXRoleAttribute)=="AXComboBox" } }
    AXUIElementSetAttributeValue(folderField,kAXValueAttribute as CFString,(destination as NSString).deletingLastPathComponent as CFString)
    try key(36)
    let save: AXUIElement=try waitFor {
        let nodes=all()
        if nodes.contains(where:{text($0,kAXIdentifierAttribute)=="PathTextField"}) {return nil}
        return nodes.first{ text($0,kAXIdentifierAttribute)=="OKButton" && ["Save","存储","保存"].contains(label($0)) && attr($0,kAXEnabledAttribute) as? Bool == true }
    }
    Thread.sleep(forTimeInterval:0.2)
    try click(save)
    var priorSize: UInt64=0,stableSince=Date()
    let _:Bool=try waitFor(45) {
        guard let attributes=try? fm.attributesOfItem(atPath:destination),let size=attributes[.size] as? UInt64,size>0 else {return nil}
        if size != priorSize {priorSize=size;stableSince=Date();return nil}
        return Date().timeIntervalSince(stableSince)>=1 ? true:nil
    }
    return ["status":"ok","saved":true]
}
do {
    guard let line=readLine(),line.utf8.count<65536,let data=line.data(using:.utf8),let request=try JSONSerialization.jsonObject(with:data) as? [String:Any] else {throw Stop(code:"ima_client_invalid_request")}
    let result=try main(request);let output=try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]);print(String(data:output,encoding:.utf8)!)
} catch let error as Stop { print("{\"status\":\"needs_attention\",\"code\":\"\(error.code)\"}") }
catch { print("{\"status\":\"needs_attention\",\"code\":\"ima_client_bridge_failed\"}") }
