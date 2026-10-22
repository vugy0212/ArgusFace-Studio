# Tab 6: O Sustavu, Sigurnosna Kopija, Hardver, GDPR i Danger Zone
import os
import sys
import shutil
import gradio as gr

import db
import config
import hardware
import backup
import notifier
from ui.theme import get_header_bar_html
from ui.common import APP_DIR, DATA_DIR

def handle_export_backup():
    try:
        zip_path = backup.export_database_zip(DATA_DIR)
        filename = os.path.basename(zip_path)
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"
        abs_path = os.path.abspath(zip_path)
        msg = (
            f"✅ **Sigurnosna kopija uspješno generirana!**\n\n"
            f"* **Datoteka:** `{filename}` ({size_str})\n"
            f"* **Lokalna putanja na disku:** `{abs_path}`\n\n"
            f"💡 *Savjet:* Datoteka je već sigurno spremljena na Vašem računalu! Kliknite na gumb **'📂 Otvori mapu sa sigurnosnim kopijama'** ispod kako biste je odmah otvorili u Windows Exploreru i premjestili ili kopirali."
        )
        return zip_path, msg
    except Exception as e:
        return None, f"❌ **Greška pri izvozu:** {e}"

def handle_open_backup_folder():
    backup_dir = os.path.abspath(os.path.join(DATA_DIR, "backups"))
    os.makedirs(backup_dir, exist_ok=True)
    if os.name == "nt":
        os.startfile(backup_dir)
        return f"📂 **Otvorena mapa sigurnosnih kopija u Windows Exploreru:** `{backup_dir}`"
    return f"📁 **Lokacija mapa sigurnosnih kopija:** `{backup_dir}`"

def handle_import_backup(file_obj):
    if not file_obj:
        return "⚠️ Niste odabrali ZIP datoteku za uvoz.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    success, msg = backup.import_database_zip(file_obj, DATA_DIR)
    table_view, stats_view = refresh_database_view()
    choices = get_person_dropdown_choices()
    sys_report = hardware.get_system_report_markdown(DATA_DIR)
    return msg, table_view, stats_view, gr.update(choices=choices, value=None), gr.update(choices=choices, value=None), sys_report

def handle_refresh_sysinfo():
    return hardware.get_hardware_acceleration_badge_html(), hardware.get_system_report_markdown(DATA_DIR)

# ---------------- DANGER ZONE HANDLERS ----------------


def _parse_retention_days(label_str: str) -> int:
    if not label_str or "Trajno" in label_str:
        return 0
    import re
    m = re.search(r"(\d+)", label_str)
    return int(m.group(1)) if m else 30

def handle_retention_period_change(val: str) -> str:
    days = _parse_retention_days(val)
    config.set_retention_days(days)
    if days == 0:
        return "ℹ️ Politika zadržavanja je postavljena na **trajno čuvanje**. Automatsko brisanje starih podataka je isključeno."
    return f"⚙️ Politika zadržavanja ažurirana: podaci stariji od **{days} dana** bit će automatski uklonjeni."

def handle_run_retention_cleanup(val: str) -> tuple:
    days = _parse_retention_days(val)
    if days == 0:
        return "⚠️ Odaberite period zadržavanja (15, 30, 60 ili 90 dana) za pokretanje čišćenja.", hardware.get_system_report_markdown(DATA_DIR)
    res = config.execute_gdpr_retention(days)
    sys_report = hardware.get_system_report_markdown(DATA_DIR)
    return res["status_message"], sys_report

# ---------------- TELEGRAM NOTIFICATION HANDLERS ----------------
def handle_save_telegram_config(enabled, token, chat_id, notify_bl, notify_vip, notify_spoof, notify_unk, cooldown, chat_id_sec="", chat_id_vip=""):
    try:
        config.save_telegram_config(
            enabled=enabled,
            bot_token=token,
            chat_id=chat_id,
            notify_blacklist=notify_bl,
            notify_vip=notify_vip,
            notify_spoof=notify_spoof,
            notify_unknown=notify_unk,
            cooldown_min=cooldown,
            chat_id_security=chat_id_sec,
            chat_id_vip=chat_id_vip
        )
        status_txt = "✅ **Telegram postavke su uspješno spremljene!**"
        if enabled:
            if not str(token or "").strip() or not str(chat_id or "").strip():
                status_txt += "\n⚠️ *Napomena:* Obavijesti su omogućene, ali Bot Token ili Chat ID nisu uneseni. Unesite ih i pošaljite testnu poruku."
            else:
                status_txt += "\n🚀 Obavijesti su aktivne! Preporučujemo da kliknete **'📨 Pošalji testnu poruku'** za provjeru veze."
        else:
            status_txt += "\nℹ️ Telegram modul je trenutno isključen."
        return status_txt
    except Exception as e:
        return f"❌ Greška pri spremanju Telegram postavki: {e}"

def handle_test_telegram(token, chat_id):
    try:
        token_str = str(token or "").strip()
        chat_str = str(chat_id or "").strip()
        if not token_str or not chat_str:
            return "⚠️ **Upozorenje:** Molimo unesite valjani Telegram Bot Token i Chat ID prije pokretanja testa."
        ok, msg = notifier.test_telegram_connection(bot_token=token_str, chat_id=chat_str)
        if ok:
            return "✅ **Testna poruka je uspješno poslana!** Provjerite svoj Telegram račun ili grupu."
        return f"⚠️ **Slanje nije uspjelo:** {msg}"
    except Exception as e:
        return f"❌ Greška pri testiranju Telegrama: {e}"

# ---------------- LOCAL API SERVICE HANDLERS ----------------
def handle_save_api_config(enabled, port, api_key):
    try:
        port_int = int(port or 5055)
        config.save_api_config(enabled=enabled, port=port_int, api_key=api_key)
        try:
            from src import api_server
            if enabled:
                ok, msg = api_server.start_api_service_background(host="0.0.0.0", port=port_int)
                return f"✅ **API postavke su spremljene!** {msg}\n\n🌐 Adresa za Docker / vanjske klijente: `http://host.docker.internal:{port_int}`"
            else:
                ok, msg = api_server.stop_api_service()
                return "ℹ️ **Lokalni API poslužitelj je isključen.** Postavke su spremljene."
        except Exception as e:
            return f"✅ Postavke su spremljene, ali je došlo do greške pri promjeni servisa: {e}"
    except Exception as e:
        return f"❌ Greška pri spremanju API postavki: {e}"

# ---------------- TELEGRAM BOT ADMIN & USER HANDLERS ----------------
def get_bot_users_dataframe_data():
    try:
        cfg = config.get_bot_config()
        users = cfg.get("allowed_users", [])
        data = []
        for u in users:
            role = "👑 Admin" if u.get("role") == "admin" else "👤 Korisnik"
            data.append([str(u.get("chat_id", "")), u.get("name", ""), role, u.get("added_at", "-")])
        return data
    except Exception:
        return []

def handle_save_bot_security(pin, timeout):
    try:
        p = str(pin or "").strip()
        if len(p) < 4:
            return "⚠️ PIN mora sadržavati najmanje 4 znaka.", get_bot_users_dataframe_data()
        cfg = config.get_bot_config()
        cfg["pin"] = p
        cfg["session_timeout_minutes"] = max(1, int(timeout or 30))
        config.save_bot_config(cfg)
        return "✅ **Sigurnosni PIN i timeout su uspješno spremljeni!**", get_bot_users_dataframe_data()
    except Exception as e:
        return f"❌ Greška: {e}", get_bot_users_dataframe_data()

def handle_add_bot_user(chat_id, name, role):
    try:
        cid_str = str(chat_id or "").strip()
        if not cid_str.isdigit():
            return "⚠️ Chat ID mora biti cijeli broj (npr. 123456789).", get_bot_users_dataframe_data(), ""
        cid = int(cid_str)
        n = str(name or "").strip() or "Korisnik"
        r = str(role or "user").strip().lower()
        
        cfg = config.get_bot_config()
        allowed = [u for u in cfg.get("allowed_users", []) if u.get("chat_id") != cid]
        admin_ids = set(cfg.get("admin_chat_ids", []))
        
        if r == "admin":
            admin_ids.add(cid)
        else:
            admin_ids.discard(cid)
            
        from datetime import datetime
        allowed.append({
            "chat_id": cid,
            "name": n,
            "role": r,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        cfg["allowed_users"] = allowed
        cfg["admin_chat_ids"] = list(admin_ids)
        config.save_bot_config(cfg)
        return f"✅ Korisnik '{n}' ({cid}) je uspješno dodan!", get_bot_users_dataframe_data(), ""
    except Exception as e:
        return f"❌ Greška: {e}", get_bot_users_dataframe_data(), ""

def handle_remove_bot_user(chat_id):
    try:
        cid_str = str(chat_id or "").strip()
        if not cid_str.isdigit():
            return "⚠️ Unesite valjani brojčani Chat ID.", get_bot_users_dataframe_data(), ""
        cid = int(cid_str)
        cfg = config.get_bot_config()
        cfg["allowed_users"] = [u for u in cfg.get("allowed_users", []) if u.get("chat_id") != cid]
        admin_ids = set(cfg.get("admin_chat_ids", []))
        admin_ids.discard(cid)
        cfg["admin_chat_ids"] = list(admin_ids)
        config.save_bot_config(cfg)
        return f"🗑️ Korisnik {cid} je uspješno uklonjen.", get_bot_users_dataframe_data(), ""
    except Exception as e:
        return f"❌ Greška: {e}", get_bot_users_dataframe_data(), ""

# ---------------- EMAIL NOTIFICATION HANDLERS ----------------
def handle_save_email_config(enabled, host, port, enc_mode, sender, password, recipients, notify_bl, notify_spoof, notify_vip, cooldown):
    try:
        use_tls = "STARTTLS" in str(enc_mode)
        use_ssl = "SSL" in str(enc_mode)
        config.save_email_config(
            enabled=enabled,
            smtp_host=str(host or "").strip(),
            smtp_port=int(port or 587),
            use_tls=use_tls,
            use_ssl=use_ssl,
            sender=str(sender or "").strip(),
            password=str(password or "").strip(),
            recipients=str(recipients or "").strip(),
            notify_blacklist=bool(notify_bl),
            notify_spoof=bool(notify_spoof),
            notify_vip=bool(notify_vip),
            cooldown_min=int(cooldown or 10)
        )
        msg = "✅ **E-mail postavke su uspješno spremljene!**"
        if enabled:
            if not str(host or "").strip() or not str(sender or "").strip() or not str(recipients or "").strip():
                msg += "\n⚠️ *Napomena:* Obavijesti su uključene, ali SMTP poslužitelj, pošiljatelj ili primatelji nisu u potpunosti uneseni."
            else:
                msg += "\n📧 Sustav je spreman. Kliknite **'📨 Pošalji testni E-mail'** za provjeru ispravnosti veze."
        else:
            msg += "\nℹ️ E-mail modul je trenutno isključen."
        return msg
    except Exception as e:
        return f"❌ Greška pri spremanju E-mail postavki: {e}"

def handle_test_email(host, port, enc_mode, sender, password, recipients):
    try:
        use_tls = "STARTTLS" in str(enc_mode)
        use_ssl = "SSL" in str(enc_mode)
        h = str(host or "").strip()
        s = str(sender or "").strip()
        r = str(recipients or "").strip()
        if not h or not s or not r:
            return "⚠️ **Upozorenje:** Unesite SMTP poslužitelj, pošiljatelja i barem jednog primatelja prije testiranja."
        ok, msg = notifier.test_email_connection(
            smtp_host=h,
            smtp_port=int(port or 587),
            use_tls=use_tls,
            use_ssl=use_ssl,
            sender=s,
            password=str(password or "").strip(),
            recipients=r
        )
        if ok:
            return f"✅ **Testni E-mail je uspješno poslan!** Provjerite ulaznu poštu ({r})."
        return f"⚠️ **Slanje nije uspjelo:** {msg}"
    except Exception as e:
        return f"❌ Greška pri slanju testnog e-maila: {e}"



def create_tab_settings():
    with gr.TabItem("ℹ️ O Sustavu i Sigurnosna Kopija"):
        with gr.Row():
            with gr.Column(scale=1):
                hw_accel_badge = gr.HTML(hardware.get_hardware_acceleration_badge_html())
                system_info_md = gr.Markdown(hardware.get_system_report_markdown(DATA_DIR))
                btn_refresh_sysinfo = gr.Button("🔄 Osvježi podatke o sustavu", size="sm")
            
                gr.Markdown("---")
                gr.Markdown(
                    """
                    ### 🎯 Sustav za maksimalnu točnost (Centroid Multi-Sample)
                    * **Sintetizirani biometrijski profil (Centroid):** Kada za osobu unesete više slika (npr. 2, 3 ili 4 različita kuta), sustav spaja njihove 512-dimenzionalne vektore u optimalni 'središnji' model osobe.
                    * **Hibridno bodovanje:** Usporedba uzima u obzir i najbolji kut i cjelokupni centroid, čime se eliminiraju lažni pozitivni rezultati i znatno povećava točnost na grupnim slikama s otežanim osvjetljenjem.
                    * **Sigurnosna margina:** Prikazuje razliku u postotku između najizglednijeg kandidata i drugog najboljeg, što daje jasan uvid u pouzdanost prepoznavanja.
                    """
                )
            with gr.Column(scale=1):
                with gr.Accordion("📦 Sigurnosna kopija i vraćanje baze (Backup & Restore ZIP)", open=False, elem_classes=["cyber-accordion"]):
                    gr.Markdown("*Kreirajte cjelovitu ZIP arhivu sustava ili obnovite postojeću bazu i fotografije.*")
                    with gr.Tabs(overflow_behavior="wrap"):
                        with gr.TabItem("💾 Izvoz (Export)"):
                            with gr.Row():
                                btn_export_backup = gr.Button("📦 Kreiraj ZIP arhivu", variant="primary", scale=3)
                                btn_open_backup_folder = gr.Button("📂 Otvori mapu (Explorer)", variant="secondary", scale=2)
                            backup_download_file = gr.File(label="Preuzmite ZIP arhivu", interactive=False, height=85, elem_classes=["compact-file"])
                            backup_export_status = gr.Markdown("")
                        
                        with gr.TabItem("📥 Vraćanje (Restore / Import)"):
                            backup_upload_file = gr.File(label="Prenesite ZIP arhivu za uvoz", file_types=[".zip"], file_count="single", height=85, elem_classes=["compact-file"])
                            btn_import_backup = gr.Button("⚠️ Uvezi arhivu i obnovi bazu", variant="stop")
                            backup_import_status = gr.Markdown("")

                with gr.Group(elem_classes=["cyber-card", "retention-card"]):
                    gr.Markdown("#### 🛡️ GDPR Upravljanje podacima i automatska rotacija (Data Retention)")
                    gr.Markdown(
                        "Uskladite pohranu sa zakonskim načelom smanjenja količine podataka (*Storage limitation*, GDPR Čl. 5(1)(e)). "
                        "Automatski ili ručno očistite zapise prolazaka, JPEG kadrove i video snimke starije od zadanog razdoblja."
                    )
                    init_ret_days = config.get_retention_days()
                    ret_choices = [
                        "15 dana (Preporučeno za video nadzor / AZOP)",
                        "30 dana (Standardno poslovno čuvanje)",
                        "60 dana",
                        "90 dana",
                        "Trajno (Bez automatskog brisanja)"
                    ]
                    init_choice = ret_choices[1]
                    if init_ret_days == 15:
                        init_choice = ret_choices[0]
                    elif init_ret_days == 30:
                        init_choice = ret_choices[1]
                    elif init_ret_days == 60:
                        init_choice = ret_choices[2]
                    elif init_ret_days == 90:
                        init_choice = ret_choices[3]
                    elif init_ret_days <= 0:
                        init_choice = ret_choices[4]

                    with gr.Row():
                        retention_period_radio = gr.Radio(
                            label="Politika zadržavanja podataka (Odaberite rok automatske rotacije)",
                            choices=ret_choices,
                            value=init_choice,
                            interactive=True,
                            elem_classes=["retention-radio-group"],
                            scale=3
                        )
                        with gr.Column(scale=2):
                            btn_run_retention = gr.Button("🧹 Očisti stare podatke odmah", variant="secondary", elem_classes=["btn-cyber-primary"])
                            retention_status_md = gr.Markdown("")

                with gr.Group(elem_classes=["cyber-card", "telegram-card"]):
                    gr.Markdown("#### 📲 Telegram Instant Sigurnosne Obavijesti")
                    gr.Markdown(
                        "Povežite Argusface sa svojim Telegram računom ili sigurnosnim kanalom za **trenutne obavijesti s fotografijom lica** "
                        "kada se detektira osoba s Crne liste, dolazak VIP uzvanika ili pokušaj lažiranja (Anti-Spoofing napad s mobitela/slike)."
                    )
                    init_tg = config.get_telegram_config()
                    telegram_enabled_chk = gr.Checkbox(
                        label="🔔 Omogući slanje obavijesti na Telegram",
                        value=init_tg["enabled"],
                        interactive=True
                    )
                    with gr.Row():
                        telegram_token_input = gr.Textbox(
                            label="Telegram Bot Token",
                            placeholder="npr. 7123456789:AAHk-...",
                            value=init_tg["bot_token"],
                            type="password",
                            scale=3,
                            info="Token dobiven od @BotFather bota"
                        )
                        telegram_chat_id_input = gr.Textbox(
                            label="Glavni Telegram Chat ID (ili ID grupe/kanala)",
                            placeholder="npr. 123456789 ili -100123456789 (moguće više odvojeno zarezom)",
                            value=init_tg["chat_id"],
                            scale=2,
                            info="Zadana adresa za obavijesti"
                        )
                    with gr.Accordion("🎯 Selektivno usmjeravanje kanala (Opcije za Zaštitare i Recepciju)", open=False, elem_classes=["cyber-accordion"]):
                        gr.Markdown(
                            "*Ostavite prazno ako svi alarmi idu u glavni Chat ID iznad.* "
                            "Upišite poseban Chat ID grupe ili korisnika kako bi samo određeni odjel primao specifične alarme."
                        )
                        with gr.Row():
                            telegram_chat_id_sec_input = gr.Textbox(
                                label="Chat ID za Službu Osiguranja / Zaštitare",
                                placeholder="npr. -10012345678 (Za Crnu listu i Anti-Spoof)",
                                value=init_tg.get("chat_id_security", ""),
                                scale=1
                            )
                            telegram_chat_id_vip_input = gr.Textbox(
                                label="Chat ID za Recepciju / Protokol",
                                placeholder="npr. -10098765432 (Za VIP dolaske)",
                                value=init_tg.get("chat_id_vip", ""),
                                scale=1
                            )
                    with gr.Row():
                        telegram_notify_blacklist_chk = gr.Checkbox(
                            label="🚨 Crna lista (Nepoželjni)",
                            value=init_tg["notify_blacklist"],
                            interactive=True
                        )
                        telegram_notify_vip_chk = gr.Checkbox(
                            label="⭐ VIP dolazak",
                            value=init_tg["notify_vip"],
                            interactive=True
                        )
                        telegram_notify_spoof_chk = gr.Checkbox(
                            label="🛡️ Pokušaj lažiranja (Anti-Spoof)",
                            value=init_tg["notify_spoof"],
                            interactive=True
                        )
                        telegram_notify_unknown_chk = gr.Checkbox(
                            label="❓ Nepoznata lica",
                            value=init_tg["notify_unknown"],
                            interactive=True
                        )
                    telegram_cooldown_slider = gr.Slider(
                        minimum=1,
                        maximum=60,
                        value=init_tg["cooldown_min"],
                        step=1,
                        label="Period hlađenja / Cooldown (minute)",
                        info="Spriječava višestruko slanje poruka za istu osobu unutar zadanog broja minuta"
                    )
                    with gr.Row():
                        btn_save_telegram_config = gr.Button("💾 Spremi postavke obavijesti", variant="primary", scale=2, elem_classes=["btn-cyber-primary"])
                        btn_test_telegram = gr.Button("📨 Pošalji testnu poruku", variant="secondary", scale=2, elem_classes=["btn-cyber-secondary"])
                    telegram_status_md = gr.Markdown("")

                with gr.Group(elem_classes=["cyber-card", "api-card"]):
                    gr.Markdown("#### 🌐 Lokalni API Poslužitelj (za Docker Telegram Bot & Vanjske Integracije)")
                    gr.Markdown(
                        "Omogućuje sigurno povezivanje vašeg **24/7 Docker Telegram Bota** ili vanjskih servisa s ArgusFace AI motorom. "
                        "Kada je omogućeno, računalo sluša zahtjeve za biometrijsku usporedbu i pretragu baze na odabranom portu."
                    )
                    init_api = config.get_api_config()
                    api_enabled_chk = gr.Checkbox(
                        label="🚀 Omogući lokalni API poslužitelj na ovom računalu",
                        value=init_api["enabled"],
                        interactive=True
                    )
                    with gr.Row():
                        api_port_input = gr.Number(
                            label="Mrežni port poslužitelja",
                            value=init_api["port"],
                            precision=0,
                            scale=1,
                            info="Zadano: 5055 (Poveznica: http://host.docker.internal:5055)"
                        )
                        api_key_input = gr.Textbox(
                            label="Sigurnosni API ključ (Opcionalno)",
                            placeholder="Ostavite prazno za nesmetan rad u lokalnoj mreži i Dockeru",
                            value=init_api["api_key"],
                            type="password",
                            scale=2,
                            info="Ako postavite ključ, bot ga mora slati u zaglavlju X-API-Key"
                        )
                    with gr.Row():
                        btn_save_api_config = gr.Button("💾 Spremi i primijeni API postavke", variant="primary", scale=2, elem_classes=["btn-cyber-primary"])
                    api_status_md = gr.Markdown("")

                    with gr.Accordion("👥 Upravljanje ovlaštenim Telegram korisnicima bota (Admin Panel)", open=False):
                        gr.Markdown(
                            "Ovdje možete odrediti tko ima pristup 24/7 Telegram botu, postaviti sigurnosni PIN, "
                            "dodijeliti uloge (Administrator / Običan korisnik) ili ukinuti pristup."
                        )
                        init_bot_cfg = config.get_bot_config()
                        with gr.Row():
                            bot_pin_input = gr.Textbox(
                                label="Sigurnosni PIN bota",
                                value=init_bot_cfg.get("pin", "121977"),
                                scale=2
                            )
                            bot_timeout_input = gr.Number(
                                label="Istek neaktivne sesije (minuta)",
                                value=init_bot_cfg.get("session_timeout_minutes", 30),
                                precision=0,
                                scale=1
                            )
                            btn_save_bot_security = gr.Button("💾 Spremi PIN i timeout", scale=1)

                        bot_users_table = gr.Dataframe(
                            headers=["Chat ID", "Ime / Opis", "Uloga", "Dodano"],
                            datatype=["str", "str", "str", "str"],
                            value=get_bot_users_dataframe_data(),
                            interactive=False,
                            label="Popis ovlaštenih Telegram korisnika bota"
                        )

                        with gr.Row():
                            new_chat_id_input = gr.Textbox(label="Novi Chat ID", placeholder="npr. 123456789", scale=2)
                            new_user_name_input = gr.Textbox(label="Ime korisnika", placeholder="npr. Marko - Zaštitar", scale=2)
                            new_user_role_dropdown = gr.Dropdown(label="Uloga", choices=["user", "admin"], value="user", scale=1)
                            btn_add_bot_user = gr.Button("➕ Dodaj korisnika", variant="primary", scale=1)

                        with gr.Row():
                            del_chat_id_input = gr.Textbox(label="Ukloni Chat ID", placeholder="Upišite Chat ID za uklanjanje", scale=3)
                            btn_del_bot_user = gr.Button("🗑️ Ukloni korisnika", variant="stop", scale=1)

                        bot_admin_status_md = gr.Markdown("")

                with gr.Group(elem_classes=["cyber-card", "email-card"]):
                    gr.Markdown("#### 📧 E-mail Sigurnosna Upozorenja (SMTP)")
                    gr.Markdown(
                        "Omogućite automatsko slanje formalnih **sigurnosnih e-mail izvještaja s priloženom slikom lica** "
                        "na službene e-mail adrese uprave, voditelja osiguranja ili vanjske zaštitarske službe."
                    )
                    init_em = config.get_email_config()
                    email_enabled_chk = gr.Checkbox(
                        label="🔔 Omogući slanje sigurnosnih e-mail upozorenja",
                        value=init_em["enabled"],
                        interactive=True
                    )
                    with gr.Row():
                        email_smtp_host = gr.Textbox(
                            label="SMTP Poslužitelj (Host)",
                            placeholder="npr. smtp.gmail.com ili smtp.office365.com",
                            value=init_em["smtp_host"],
                            scale=3
                        )
                        email_smtp_port = gr.Number(
                            label="Port",
                            value=init_em["smtp_port"],
                            precision=0,
                            scale=1
                        )
                        enc_default = "STARTTLS (Port 587)" if init_em["use_tls"] else ("SSL / TLS (Port 465)" if init_em["use_ssl"] else "Bez enkripcije")
                        email_encryption_radio = gr.Radio(
                            label="Enkripcija",
                            choices=["STARTTLS (Port 587)", "SSL / TLS (Port 465)", "Bez enkripcije"],
                            value=enc_default,
                            scale=2
                        )
                    with gr.Row():
                        email_sender = gr.Textbox(
                            label="Pošiljatelj (Korisničko ime / Email)",
                            placeholder="npr. argusface.sigurnost@firma.hr",
                            value=init_em["sender"],
                            scale=3
                        )
                        email_password = gr.Textbox(
                            label="Lozinka / App Password",
                            type="password",
                            placeholder="Lozinka ili Google App Password",
                            value=init_em["password"],
                            scale=3
                        )
                    email_recipients = gr.Textbox(
                        label="Primatelji upozorenja (jedan ili više e-mailova odvojenih zarezom)",
                        placeholder="npr. zastita@firma.hr, voditelj.osiguranja@firma.hr, direktor@firma.hr",
                        value=init_em["recipients"],
                        info="Sve navedene adrese primit će formatiran HTML e-mail s detaljima i slikom incidenta"
                    )
                    with gr.Row():
                        email_notify_blacklist_chk = gr.Checkbox(
                            label="🚨 Crna lista (Nepoželjni)",
                            value=init_em["notify_blacklist"],
                            interactive=True
                        )
                        email_notify_spoof_chk = gr.Checkbox(
                            label="🛡️ Pokušaj lažiranja (Anti-Spoof)",
                            value=init_em["notify_spoof"],
                            interactive=True
                        )
                        email_notify_vip_chk = gr.Checkbox(
                            label="⭐ VIP dolazak",
                            value=init_em["notify_vip"],
                            interactive=True
                        )
                    email_cooldown_slider = gr.Slider(
                        minimum=1,
                        maximum=60,
                        value=init_em["cooldown_min"],
                        step=1,
                        label="Period hlađenja / Cooldown (minute)",
                        info="Spriječava preopterećenje pretinca uzastopnim porukama za istu osobu"
                    )
                    with gr.Row():
                        btn_save_email_config = gr.Button("💾 Spremi E-mail postavke", variant="primary", scale=2, elem_classes=["btn-cyber-primary"])
                        btn_test_email = gr.Button("📨 Pošalji testni E-mail", variant="secondary", scale=2, elem_classes=["btn-cyber-secondary"])
                    email_status_md = gr.Markdown("")

        gr.Markdown("---")
        with gr.Accordion("⚖️ Pravne napomene, licence i regulatorna usklađenost (GDPR & EU AI Act)", open=True, elem_classes=["cyber-accordion"]):
            gr.Markdown(
                """
                ### 📜 Komercijalne licence AI modela i tehnološkog stoga
                ArgusFace Studio je konfiguriran s fokusom na **100% legalnu, čistu i sigurnu komercijalnu primjenu** bez akademskih ograničenja ili skrivenih naknada:
                * **Detekcija lica (RetinaFace):** Licencirano pod **MIT licencom**. Omogućuje ultra-brzo i robusno pronalaženje lica i ključnih točaka.
                * **Prepoznavanje lica (EdgeFace BASE):** Licencirano pod **BSD-3-Clause licencom** (*Idiap Research Institute*, Švicarska). Generira 512-dimenzionalne normalizirane biometrijske vektore uz točnost od **99.83%** na LFW standardu.
                * **Inženjerski i grafički stog:** Razvijeno u Pythonu uz **OpenCV** i **ONNX Runtime** (oba pod **Apache 2.0** licencom).
                * **Distribucija i komercijalizacija:** Cjelokupni stog modela i biblioteka slobodan je za komercijalnu prodaju, instalaciju kod klijenata i licenciranje trećim stranama.

                ---

                ### 🛡️ Zaštita osobnih i biometrijskih podataka (GDPR usklađenost)
                * **100% Lokalna obrada (Edge / On-Premise):** Sva obrada slika, video tokova i biometrijskih vektora odvija se isključivo na lokalnom računalu. Niti jedan podatak, slika ili vektor nikada se ne prenosi na vanjske poslužitelje ili Cloud.
                * **Biometrijski podaci (Članak 9. GDPR-a):** 512-D vektori tretiraju se kao biometrijski podaci. Korisnik/vlasnik sustava odgovoran je za zakonitost prikupljanja (odgovarajuća privola ili zakonska pravna osnova).
                * **Pravo na zaborav:** Sustav omogućuje trajno, nepovratno brisanje pojedinačnih uzoraka ili cjelokupnih profila osoba iz baze podataka jednim klikom.

                ---

                ### 🇪🇺 Usklađenost sa Zakonom o umjetnoj inteligenciji (EU AI Act)
                * **Klasifikacija sustava:** ArgusFace Studio namijenjen je za privatnu i internu poslovnu upotrebu (npr. organizacija arhive fotografija, evidencija prisutnosti i verifikacija u kontroliranim privatnim prostorima).
                * **Ograničenje namjene:** Sustav nije namijenjen niti licenciran za neovlašteno masovno biometrijsko profiliranje ili prepoznavanje u stvarnom vremenu na javno dostupnim površinama.
                """
            )



    return {
        "hw_accel_badge": hw_accel_badge,
        "system_info_md": system_info_md,
        "btn_refresh_sysinfo": btn_refresh_sysinfo,
        "btn_export_backup": btn_export_backup,
        "btn_open_backup_folder": btn_open_backup_folder,
        "backup_download_file": backup_download_file,
        "backup_export_status": backup_export_status,
        "backup_upload_file": backup_upload_file,
        "btn_import_backup": btn_import_backup,
        "backup_import_status": backup_import_status,
        "retention_period_radio": retention_period_radio,
        "btn_run_retention": btn_run_retention,
        "retention_status_md": retention_status_md,
        "telegram_enabled_chk": telegram_enabled_chk,
        "telegram_token_input": telegram_token_input,
        "telegram_chat_id_input": telegram_chat_id_input,
        "telegram_chat_id_sec_input": telegram_chat_id_sec_input,
        "telegram_chat_id_vip_input": telegram_chat_id_vip_input,
        "telegram_notify_blacklist_chk": telegram_notify_blacklist_chk,
        "telegram_notify_vip_chk": telegram_notify_vip_chk,
        "telegram_notify_spoof_chk": telegram_notify_spoof_chk,
        "telegram_notify_unknown_chk": telegram_notify_unknown_chk,
        "telegram_cooldown_slider": telegram_cooldown_slider,
        "btn_save_telegram_config": btn_save_telegram_config,
        "btn_test_telegram": btn_test_telegram,
        "telegram_status_md": telegram_status_md,
        "api_enabled_chk": api_enabled_chk,
        "api_port_input": api_port_input,
        "api_key_input": api_key_input,
        "btn_save_api_config": btn_save_api_config,
        "api_status_md": api_status_md,
        "bot_pin_input": bot_pin_input,
        "bot_timeout_input": bot_timeout_input,
        "btn_save_bot_security": btn_save_bot_security,
        "bot_users_table": bot_users_table,
        "new_chat_id_input": new_chat_id_input,
        "new_user_name_input": new_user_name_input,
        "new_user_role_dropdown": new_user_role_dropdown,
        "btn_add_bot_user": btn_add_bot_user,
        "del_chat_id_input": del_chat_id_input,
        "btn_del_bot_user": btn_del_bot_user,
        "bot_admin_status_md": bot_admin_status_md,
        "email_enabled_chk": email_enabled_chk,
        "email_smtp_host": email_smtp_host,
        "email_smtp_port": email_smtp_port,
        "email_encryption_radio": email_encryption_radio,
        "email_sender": email_sender,
        "email_password": email_password,
        "email_recipients": email_recipients,
        "email_notify_blacklist_chk": email_notify_blacklist_chk,
        "email_notify_spoof_chk": email_notify_spoof_chk,
        "email_notify_vip_chk": email_notify_vip_chk,
        "email_cooldown_slider": email_cooldown_slider,
        "btn_save_email_config": btn_save_email_config,
        "btn_test_email": btn_test_email,
        "email_status_md": email_status_md,
    }

def wire_tab_settings_events(c):
    c['btn_refresh_sysinfo'].click(
        fn=handle_refresh_sysinfo,
        outputs=[c['hw_accel_badge'], c['system_info_md']]
    )

    c['btn_export_backup'].click(
        fn=handle_export_backup,
        outputs=[c['backup_download_file'], c['backup_export_status']]
    )

    c['btn_open_backup_folder'].click(
        fn=handle_open_backup_folder,
        outputs=[c['backup_export_status']]
    )

    c['btn_import_backup'].click(
        fn=handle_import_backup,
        inputs=[c['backup_upload_file']],
        outputs=[c['backup_import_status'], c['db_table'], c['db_stats_md'], c['manage_person_dropdown'], c['existing_person_picker'], c['system_info_md']]
    ).then(
        fn=get_header_bar_html,
        outputs=[c['top_header_bar']]
    )

    c['retention_period_radio'].change(
        fn=handle_retention_period_change,
        inputs=[c['retention_period_radio']],
        outputs=[c['retention_status_md']]
    )

    c['btn_run_retention'].click(
        fn=handle_run_retention_cleanup,
        inputs=[c['retention_period_radio']],
        outputs=[c['retention_status_md'], c['system_info_md']]
    )

    c['btn_save_telegram_config'].click(
        fn=handle_save_telegram_config,
        inputs=[
            c['telegram_enabled_chk'],
            c['telegram_token_input'],
            c['telegram_chat_id_input'],
            c['telegram_notify_blacklist_chk'],
            c['telegram_notify_vip_chk'],
            c['telegram_notify_spoof_chk'],
            c['telegram_notify_unknown_chk'],
            c['telegram_cooldown_slider'],
            c['telegram_chat_id_sec_input'],
            c['telegram_chat_id_vip_input']
        ],
        outputs=[c['telegram_status_md']]
    )

    c['btn_test_telegram'].click(
        fn=handle_test_telegram,
        inputs=[c['telegram_token_input'], c['telegram_chat_id_input']],
        outputs=[c['telegram_status_md']]
    )

    c['btn_save_api_config'].click(
        fn=handle_save_api_config,
        inputs=[
            c['api_enabled_chk'],
            c['api_port_input'],
            c['api_key_input']
        ],
        outputs=[c['api_status_md']]
    )

    c['btn_save_bot_security'].click(
        fn=handle_save_bot_security,
        inputs=[c['bot_pin_input'], c['bot_timeout_input']],
        outputs=[c['bot_admin_status_md'], c['bot_users_table']]
    )

    c['btn_add_bot_user'].click(
        fn=handle_add_bot_user,
        inputs=[c['new_chat_id_input'], c['new_user_name_input'], c['new_user_role_dropdown']],
        outputs=[c['bot_admin_status_md'], c['bot_users_table'], c['new_chat_id_input']]
    )

    c['btn_del_bot_user'].click(
        fn=handle_remove_bot_user,
        inputs=[c['del_chat_id_input']],
        outputs=[c['bot_admin_status_md'], c['bot_users_table'], c['del_chat_id_input']]
    )

    c['btn_save_email_config'].click(
        fn=handle_save_email_config,
        inputs=[
            c['email_enabled_chk'],
            c['email_smtp_host'],
            c['email_smtp_port'],
            c['email_encryption_radio'],
            c['email_sender'],
            c['email_password'],
            c['email_recipients'],
            c['email_notify_blacklist_chk'],
            c['email_notify_spoof_chk'],
            c['email_notify_vip_chk'],
            c['email_cooldown_slider']
        ],
        outputs=[c['email_status_md']]
    )

    c['btn_test_email'].click(
        fn=handle_test_email,
        inputs=[
            c['email_smtp_host'],
            c['email_smtp_port'],
            c['email_encryption_radio'],
            c['email_sender'],
            c['email_password'],
            c['email_recipients']
        ],
        outputs=[c['email_status_md']]
    )
