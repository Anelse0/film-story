// 把 PDF 每一行的文字连同位置打出来（只读），供 screenplay_pages.py 按缩进还原剧本元素。
// 用法：swift pdf_lines.swift <文件.pdf>
// 输出：每页一行 "=== PAGE n<TAB>宽<TAB>高"，随后每行文字一行 "左<TAB>右<TAB>底<TAB>顶<TAB>文字"（单位 pt，原点在页面左下角）。
import Foundation
import PDFKit

guard CommandLine.arguments.count > 1,
      let doc = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    FileHandle.standardError.write("cannot open pdf\n".data(using: .utf8)!)
    exit(1)
}
for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i) else { continue }
    let box = page.bounds(for: .mediaBox)
    print("=== PAGE \(i + 1)\t\(Int(box.width.rounded()))\t\(Int(box.height.rounded()))")
    guard let all = page.selection(for: box) else { continue }
    for line in all.selectionsByLine() {
        let r = line.bounds(for: page)
        let text = (line.string ?? "").replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
        if text.isEmpty { continue }
        print("\(Int(r.minX.rounded()))\t\(Int(r.maxX.rounded()))\t\(Int(r.minY.rounded()))\t\(Int(r.maxY.rounded()))\t\(text)")
    }
}
