# -*- coding: utf-8 -*-
"""
Skripta za generiranje profesionalnog Word dokumenta (.docx):
ArgusFace Studio — Arhitektura Sustava, Povezanost s Telegram Botom i Mini Web Appom
"""

import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def set_cell_background(cell, color_hex):
    """Postavlja boju pozadine tablične ćelije."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=140, bottom=140, left=200, right=200):
    """Postavlja unutarnje margine ćelije u dxa (1 pt = 20 dxa)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}>'
                      f'<w:top w:w="{top}" w:type="dxa"/>'
                      f'<w:left w:w="{left}" w:type="dxa"/>'
                      f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
                      f'<w:right w:w="{right}" w:type="dxa"/>'
                      f'</w:tcMar>')
    tcPr.append(tcMar)

def set_table_borders(table, color="CBD5E1", sz="4", val="single"):
    """Postavlja suptilne rubove tablice."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(f'<w:tblBorders {nsdecls("w")}>'
                        f'<w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
                        f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
                        f'<w:left w:val="none"/>'
                        f'<w:right w:val="none"/>'
                        f'<w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
                        f'<w:insideV w:val="none"/>'
                        f'</w:tblBorders>')
    tblPr.append(borders)

def add_callout(doc, text_paragraphs, title="VAŽNA NAPOMENA", border_color="0284C7", bg_color="F8FAFC"):
    """Kreira vizualno istaknuti callout okvir s obojanom lijevom trakom."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Inches(6.5)

    cell = tbl.cell(0, 0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=160, bottom=160, left=220, right=220)

    # Postavi samo lijevi debeli border
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(f'<w:tcBorders {nsdecls("w")}>'
                        f'<w:top w:val="none"/>'
                        f'<w:bottom w:val="none"/>'
                        f'<w:right w:val="none"/>'
                        f'<w:left w:val="single" w:sz="32" w:space="0" w:color="{border_color}"/>'
                        f'</w:tcBorders>')
    tcPr.append(borders)

    # Naslov okvira
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    run_t = p.add_run(f"📌 {title}\n")
    run_t.font.name = "Segoe UI"
    run_t.font.size = Pt(10.5)
    run_t.font.bold = True
    run_t.font.color.rgb = RGBColor(15, 23, 42)

    # Sadržaj
    for idx, t in enumerate(text_paragraphs):
        if idx > 0:
            p = cell.add_paragraph()
        run = p.add_run(t)
        run.font.name = "Segoe UI"
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(51, 65, 85)
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def main():
    doc = docx.Document()

    # Postavke stranice (A4, margine 2.5 cm)
    for section in doc.sections:
        section.page_width = Inches(8.27)   # A4 širina
        section.page_height = Inches(11.69) # A4 visina
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    # Globalni stil Normal
    style_normal = doc.styles['Normal']
    font = style_normal.font
    font.name = 'Segoe UI'
    font.size = Pt(10)
    font.color.rgb = RGBColor(30, 41, 59) # Slate 800

    # -------------------------------------------------------------
    # ZAGLAVLJE DOKUMENTA
    # -------------------------------------------------------------
    header_p = doc.add_paragraph()
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header_run = header_p.add_run("ARGUSFACE STUDIO  |  TEHNIČKA ARHITEKTURA I PRIRUČNIK")
    header_run.font.size = Pt(8.5)
    header_run.font.bold = True
    header_run.font.color.rgb = RGBColor(100, 116, 139)
    header_p.paragraph_format.space_after = Pt(12)

    # GLAVNI NASLOV DOKUMENTA
    title_p = doc.add_paragraph()
    title_run = title_p.add_run("ArgusFace Studio — Arhitektura Sustava")
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(15, 23, 42) # Deep slate
    title_p.paragraph_format.space_after = Pt(2)

    subtitle_p = doc.add_paragraph()
    sub_run = subtitle_p.add_run("Povezanost Desktop Aplikacije, Telegram Bota i Mini Web Appa: Kako funkcioniraju i kako se instaliraju")
    sub_run.font.size = Pt(12.5)
    sub_run.font.color.rgb = RGBColor(2, 132, 199) # Sky blue
    subtitle_p.paragraph_format.space_after = Pt(16)

    # Metadata bar
    meta_p = doc.add_paragraph()
    meta_run = meta_p.add_run("Verzija dokumenta: 1.2  •  Datum: Listopad 2026.  •  Status: Službena arhitekturna specifikacija")
    meta_run.font.size = Pt(9)
    meta_run.font.italic = True
    meta_run.font.color.rgb = RGBColor(100, 116, 139)
    meta_p.paragraph_format.space_after = Pt(16)

    # -------------------------------------------------------------
    # 1. UVOD I SAŽETAK (EXECUTIVE SUMMARY)
    # -------------------------------------------------------------
    h1 = doc.add_heading("1. Uvod i Sažetak za Korisnika", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph(
        "Jedno od najčešćih pitanja pri razmatranju ovakvog biometrijskog sustava glasi: "
        "„Je li desktop aplikacija zaseban program, a Telegram bot i Mini Web App nešto što kupac mora sam razvijati i programirati?”\n"
        "Kratak i jasan odgovor je: NE, korisnik ne mora ništa sam razvijati! "
        "ArgusFace Studio je cjelovito programsko rješenje „ključ u ruke” (turnkey solution) "
        "u kojem su sve tri komponente već u potpunosti izgrađene, integrirane i tvornički usklađene."
    )
    p.paragraph_format.space_after = Pt(8)

    add_callout(
        doc,
        [
            "Sve tri komponente (Desktop sučelje, Telegram bot i Mini Web App) već su 100% programirane.",
            "Krajnji korisnik ili kupac ne piše niti jednu liniju programskog koda.",
            "Lokalni API poslužitelj nalazi se ugrađen unutar same desktop aplikacije i pokreće se automatski.",
            "Korisnik samo unosi svoj Telegram Bot Token (koji besplatno preuzme od @BotFathera) i sigurnosni PIN u grafičkim postavkama."
        ],
        title="KLJUČNO PRAVILO SUSTAVA",
        border_color="0284C7",
        bg_color="F0F9FF"
    )

    # -------------------------------------------------------------
    # 2. ULOGA POJEDINIH KOMPONENTI
    # -------------------------------------------------------------
    h1 = doc.add_heading("2. Uloge i Odgovornosti Triju Komponenti", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)

    # Komponenta 1
    h2 = doc.add_heading("2.1. Glavna Desktop Aplikacija (ArgusFace Studio — „Mozak”)", level=2)
    h2.style.font.size = Pt(12)
    h2.style.font.bold = True
    h2.style.font.color.rgb = RGBColor(15, 23, 42)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph(
        "Glavna aplikacija instalirana je na operacijskom računalu (Windows). Ona predstavlja središnje čvorište i sadrži:"
    )
    doc.add_paragraph("• AI Biometrijski motor (EdgeFace / UniFace): Visokotočni konvolucijski modeli za izdvajanje 512-dimenzionalnih vektora lica, procjenu dobi, spola i detekciju autentičnosti (anti-spoofing).", style='List Bullet')
    doc.add_paragraph("• Lokalnu bazu podataka (SQLite database.db): Sigurno lokalno spremište bez ovisnosti o oblaku, koje čuva osobe, uloge (Standard, VIP, Crna lista), bilješke i galerije slika.", style='List Bullet')
    doc.add_paragraph("• FAISS HNSW vektorski indeks: Grafički indeks za pretraživanje baze u djeliću milisekunde čak i s desecima tisuća lica.", style='List Bullet')
    doc.add_paragraph("• Ugrađeni FastAPI poslužitelj (Port 5055): Sluša lokalne zahtjeve i povezuje vanjski svijet s biometrijskim motorom.", style='List Bullet')

    # Komponenta 2
    h2 = doc.add_heading("2.2. Mini Web App (Mobilno sučelje bez instalacije)", level=2)
    h2.style.font.size = Pt(12)
    h2.style.font.bold = True
    h2.style.font.color.rgb = RGBColor(15, 23, 42)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph(
        "Mini Web App je lagana, moderna web aplikacija prilagođena mobitelima i tabletima. "
        "Ona se NE nalazi na nikakvom zakupljenom vanjskom serveru, već je smještena izravno u mapi webapp/ na vašem računalu. "
        "Ugrađeni API poslužitelj samostalno je servira preko preglednika ili unutar Telegrama.\n"
        "Funkcionalnosti Mini Web Appa uključuju:"
    )
    doc.add_paragraph("• Brzo foto skeniranje lica (1:N) s kamere mobitela ili galerije uz trenutni prikaz vizualnih kartica.", style='List Bullet')
    doc.add_paragraph("• Biometrijsku 1:1 usporedbu dvaju lica s postotkom podudaranja.", style='List Bullet')
    doc.add_paragraph("• 1-Tap registraciju novih lica ili dodavanje uzoraka postojećim profilima izravno s terena.", style='List Bullet')
    doc.add_paragraph("• Pregled statusa sustava i baze registriranih osoba u stvarnom vremenu.", style='List Bullet')

    # Komponenta 3
    h2 = doc.add_heading("2.3. Telegram Bot (24/7 Terenska kontrola i obavijesti)", level=2)
    h2.style.font.size = Pt(12)
    h2.style.font.bold = True
    h2.style.font.color.rgb = RGBColor(15, 23, 42)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph(
        "Telegram Bot radi kao siguran posrednik između ovlaštenih djelatnika na terenu i glavnog računala. "
        "Djelatnik ne mora instalirati nikakvu posebnu aplikaciju iz trgovine aplikacijama — koristi običan Telegram.\n"
        "Glavne značajke bota:"
    )
    doc.add_paragraph("• Slanje fotografije izravno u chat: Bot u roku sekunde vraća ime, ulogu, status (VIP / Crna lista), vizualni grafički postotak sličnosti i provjeru autentičnosti lica.", style='List Bullet')
    doc.add_paragraph("• Nativni izbornik naredbi (/menu, /scan, /compare, /enroll, /database, /status, /lock).", style='List Bullet')
    doc.add_paragraph("• Stroga sigurnost: Višeslojna PIN zaštita sa sesijskim timeoutom i anti-bruteforce blokadom (nakon 5 krivih unosa bot se privremeno zaključava).", style='List Bullet')
    doc.add_paragraph("• Odobrenje pristupa u 1 klik: Novi korisnik može zatražiti pristup, a administrator ga u chat-u jednim klikom odobrava.", style='List Bullet')

    # -------------------------------------------------------------
    # 3. KAKO KOMPONENTE MEĐUSOBNO KOMUNICIRAJU
    # -------------------------------------------------------------
    h1 = doc.add_heading("3. Arhitektura Povezanosti i Tijek Podataka", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph(
        "Povezanost sustava temelji se na klijentsko-poslužiteljskoj arhitekturi (Client-Server). "
        "Sve komponente govore istim standardnim protokolom (HTTP/JSON REST API)."
    )
    p.paragraph_format.space_after = Pt(6)

    # ASCII Dijagram toka
    diag_p = doc.add_paragraph()
    diag_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    diag_run = diag_p.add_run(
        "┌────────────────────────────────────────────────────────────────────────┐\n"
        "│                          MOBILNI KORISNIK                              │\n"
        "│       [ Telegram Aplikacija ]        ili      [ Mobilni Preglednik ]   │\n"
        "│           (Telegram Bot)                           (Mini Web App)      │\n"
        "└───────────────────────────────┬────────────────────────────────────────┘\n"
        "                                │\n"
        "                                ▼  (Sigurna HTTPS veza / Lokalni Wi-Fi)\n"
        "┌────────────────────────────────────────────────────────────────────────┐\n"
        "│              LOKALNI REST API POSLUŽITELJ (Port 5055)                  │\n"
        "│         FastAPI poslužitelj ugrađen u sam ArgusFace Studio             │\n"
        "└───────────────────────────────┬────────────────────────────────────────┘\n"
        "                                │\n"
        "                                ▼  (Direktna međusobna komunikacija)\n"
        "┌────────────────────────────────────────────────────────────────────────┐\n"
        "│                   ARGUSFACE STUDIO AI MOTOR & BAZA                     │\n"
        "│   • UniFace / EdgeFace modeli (512-D)  • Anti-Spoofing Liveness        │\n"
        "│   • SQLite Baza (database.db)          • FAISS Vektorski Indeks        │\n"
        "└────────────────────────────────────────────────────────────────────────┘"
    )
    diag_run.font.name = "Consolas"
    diag_run.font.size = Pt(8.5)
    diag_run.font.color.rgb = RGBColor(30, 41, 59)
    diag_p.paragraph_format.space_after = Pt(10)

    # Koraci komunikacije
    p = doc.add_paragraph()
    p.add_run("Tijek jedne biometrijske provjere odvija se u sljedećim koracima:\n").bold = True
    doc.add_paragraph("1. Snimanje fotografije: Korisnik na mobitelu slika osobu i šalje je botu ili u Mini Web App.", style='List Bullet')
    doc.add_paragraph("2. Slanje na računalo: Slika se kriptiranim kanalom šalje na lokalni API port 5055.", style='List Bullet')
    doc.add_paragraph("3. AI Ekstrakcija i Pretraga: Lokalni motor detektira lica, provjerava autentičnost i uspoređuje vektor s FAISS bazom.", style='List Bullet')
    doc.add_paragraph("4. Dvostrana sinkronizacija: Zahvaljujući ugrađenoj SQLite 'PRAGMA data_version' sinkronizaciji, čim operater doda novo lice na računalu, bot ga u istom trenutku prepoznaje.", style='List Bullet')
    doc.add_paragraph("5. Rezultat u sekundi: Bot ili Web App vraća karticu s označenim licem, postotkom podudaranja i sigurnosnom ulogom.", style='List Bullet')

    # -------------------------------------------------------------
    # 4. KAKO SE INSTALIRAJU I POKREĆU (ZA KRAJNJEG KORISNIKA)
    # -------------------------------------------------------------
    h1 = doc.add_heading("4. Instalacija i Puštanje u Rad", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph(
        "Kada se bude radila konačna instalacijska datoteka (Setup čarobnjak) za kupce, "
        "cilj je da korisničko iskustvo bude maksimalno jednostavno i bez potrebe za informatičkim predznanjem."
    )
    p.paragraph_format.space_after = Pt(6)

    h2 = doc.add_heading("4.1. Što radi instalacijski paket (Setup.exe)?", level=2)
    h2.style.font.size = Pt(12)
    h2.style.font.bold = True
    h2.style.font.color.rgb = RGBColor(15, 23, 42)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)

    doc.add_paragraph("1. Kopira izvršne datoteke, grafičko sučelje, gotove AI modele i mapu webapp/.", style='List Number')
    doc.add_paragraph("2. Kreira prečac na radnoj površini (Desktop Shortcut).", style='List Number')
    doc.add_paragraph("3. Postavlja lokalni API poslužitelj da se automatski, nečujno pokreće u pozadini pri paljenju Windowsa (Autostart Windows Task / Servis).", style='List Number')
    doc.add_paragraph("4. Integrira gotovu skriptu Telegram bota koja komunicira s lokalnim API-jem.", style='List Number')

    h2 = doc.add_heading("4.2. Korisnički koraci nakon instalacije (Samo 3 minute posla)", level=2)
    h2.style.font.size = Pt(12)
    h2.style.font.bold = True
    h2.style.font.color.rgb = RGBColor(15, 23, 42)
    h2.paragraph_format.space_before = Pt(8)
    h2.paragraph_format.space_after = Pt(4)

    p = doc.add_paragraph(
        "Nakon instalacije, korisnik mora napraviti samo sljedeća tri koraka u grafičkom sučelju:"
    )

    doc.add_paragraph("• Korak 1 — Preuzimanje Tokena: Korisnik otvori svoj Telegram, potraži @BotFather (službeni Telegramov servis za izradu botova), pošalje /newbot i upiše željeno ime svog bota. BotFather mu odmah vrati Bot Token (dugački niz slova i brojeva).", style='List Bullet')
    doc.add_paragraph("• Korak 2 — Unos u Postavke: Korisnik otvori ArgusFace Studio, klikne tab 'Postavke' -> 'Telegram & API', zalijepi svoj Bot Token i unese proizvoljni 6-znamenkasti PIN (npr. 123456).", style='List Bullet')
    doc.add_paragraph("• Korak 3 — Pokretanje: Klikne gumb '🟢 Spremi i pokreni Bot'. Od tog trenutka bot i web aplikacija su aktivni i spremni za rad!", style='List Bullet')

    add_callout(
        doc,
        [
            "U razvoju trenutno koristimo Docker radi praktičnosti i izolacije okruženja.",
            "U konačnom instalacijskom paketu za krajnjeg kupca Docker NIJE obavezan — bot se može pokretati kao običan tihi pozadinski Windows proces (npr. putem pythonw.exe ili Windows Servisa), tako da kupac ne mora instalirati ništa osim samog ArgusFace programa."
        ],
        title="DOCKER VS. WINDOWS INSTALACIJA",
        border_color="10B981", # Emerald green
        bg_color="F0FDF4"
    )

    # -------------------------------------------------------------
    # 5. TABLICA USPOREDBE I ODGOVORNOSTI
    # -------------------------------------------------------------
    h1 = doc.add_heading("5. Sažeti Pregled Komponenti", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)

    table_data = [
        ["Komponenta", "Gdje se nalazi?", "Mora li je korisnik programirati?", "Glavna svrha i funkcija"],
        ["Desktop GUI (ArgusFace)", "Glavno računalo", "NE (Gotov program)", "Upravljanje bazom, kamere uživo, izvoz izvještaja, sigurnosne kopije, AI motor."],
        ["Lokalni REST API", "Glavno računalo (Port 5055)", "NE (Ugrađeno u program)", "Pozadinski poslužitelj koji prima slike, pretražuje bazu i vraća rezultate."],
        ["Mini Web App", "Mapa webapp/ na računalu", "NE (Gotov HTML/JS/CSS)", "Mobilno web sučelje za skeniranje s mobitela, 1:1 usporedbu i brzi unos lica."],
        ["Telegram Bot", "Radi u pozadini na PC-ju", "NE (Gotov Python modul)", "24/7 pristup s mobitela preko Telegrama uz PIN zaštitu i nativni meni naredbi."],
        ["Vanjski API klijenti", "Bilo koji vanjski sustav", "OPCIONALNO (Za integratore)", "Ako treća strana želi spojiti svoja automatska vrata, rampu ili aplikaciju."]
    ]

    table = doc.add_table(rows=len(table_data), cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)

    col_widths = [Inches(1.5), Inches(1.3), Inches(1.4), Inches(2.3)]

    for row_idx, row in enumerate(table.rows):
        is_header = (row_idx == 0)
        trPr = row._tr.get_or_add_trPr()
        trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

        for col_idx, cell in enumerate(row.cells):
            cell.width = col_widths[col_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_margins(cell, top=100, bottom=100, left=120, right=120)

            val = table_data[row_idx][col_idx]
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)

            run = p.add_run(val)
            run.font.name = "Segoe UI"
            run.font.size = Pt(8.5)

            if is_header:
                set_cell_background(cell, "1E3A8A")
                run.font.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
            else:
                bg = "F8FAFC" if row_idx % 2 == 1 else "FFFFFF"
                set_cell_background(cell, bg)
                if col_idx == 2 and "NE" in val:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(16, 185, 129) # Zeleno
                elif col_idx == 0:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(15, 23, 42)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # -------------------------------------------------------------
    # 6. ZAKLJUČAK
    # -------------------------------------------------------------
    h1 = doc.add_heading("6. Zaključak", level=1)
    h1.style.font.size = Pt(14)
    h1.style.font.bold = True
    h1.style.font.color.rgb = RGBColor(30, 58, 138)
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)

    p = doc.add_paragraph(
        "Kroz ovakvu arhitekturu ArgusFace Studio postiže najbolje od oba svijeta: "
        "krajnjem kupcu nudi jednostavnost gotovog proizvoda bez programiranja, "
        "dok istovremeno nudi profesionalnu modularnost i moćni API za napredne korisnike i integratore."
    )
    p.paragraph_format.space_after = Pt(6)

    # Spremanje dokumenta
    out_path = r"c:\ArgusFace Studio\ArgusFace_Studio_Arhitektura_Povezanost_i_Instalacija.docx"
    doc.save(out_path)
    print(f"Uspjesno generiran dokument: {out_path}")

if __name__ == "__main__":
    main()
