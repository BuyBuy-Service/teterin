# Доводит документы через Microsoft Office: обновляет оглавление и поля в .docx, сохраняет PDF-копии
# для проверки. Использование: powershell -File report\finalize.ps1 <файл.docx|файл.pptx> ...
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)

foreach ($f in $Files) {
    $path = (Resolve-Path $f).Path
    $pdf = [IO.Path]::ChangeExtension($path, ".pdf")
    if ($path -like "*.docx") {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        try {
            $doc = $word.Documents.Open($path)
            $doc.Fields.Update() | Out-Null
            foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
            $doc.Fields.Update() | Out-Null
            $doc.Save()
            $doc.ExportAsFixedFormat($pdf, 17)   # 17 = PDF
            "pages: " + $doc.ComputeStatistics(2)
            $doc.Close()
        } finally { $word.Quit() }
    } elseif ($path -like "*.pptx") {
        $pp = New-Object -ComObject PowerPoint.Application
        try {
            $pres = $pp.Presentations.Open($path, $true, $false, $false)  # только чтение, без окна
            $pres.SaveAs($pdf, 32)                                        # 32 = PDF
            "slides: " + $pres.Slides.Count
            $pres.Close()
        } finally { $pp.Quit() }
    }
    "ok: $pdf"
}
