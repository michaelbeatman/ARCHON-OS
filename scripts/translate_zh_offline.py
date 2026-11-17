#!/usr/bin/env python3
"""Offline ZH-Uebersetzung (eigenes Wissen, kein API-Call). Ablauf wie translate_manual.py."""
import json, os, re, sys, copy
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir("C:/.Antigravity-projekte/AgenticOS-2026")
from scripts.translate_manual import (
    should_skip_text, merge_adjacent_similar_runs,
    export_pdf_and_update_glossary_windows, NS, LANG_META,
)

CACHE = "data/translation_cache_zh.json"
TOC_TITLE = "目录"
LOCALE = "zh-CN"
TAG = "ZH"
PREFIX = "第"
BATCH = 18

LOCKS = ["Archon OS","Mission Control","Decision Engine","Showroom","Research Lab",
    "Token Guard","System Control Center","Hermes Core","OmniRoute","AnythingLLM",
    "ChromaDB","PocketBase","Obsidian","n8n","Caddy","Authelia",
    "RBAC","TLS","AES","PBKDF2-HMAC-SHA256","Argon2id","SHA-256","RAG","CRM","ERP",
    "DATEV","MCP","API","OKR","company_id","break_glass_vault.enc",
    "admin","operator","viewer","v0.5.1"]

PHRASE_MAP = [
 ("Alphabetisches Glossar & Stichwortverzeichnis","按字母排序的术语表与索引"),
 ("Glossar & Alphabetisches Framework-Verzeichnis","术语表与框架字母索引"),
 ("Versionsstand & Release-Übersicht","版本状态与发布概述"),
 ("System-Ansichten & Spezial-Studios","系统视图与专用工作室"),
 ("UI Views","UI 视图"),
 ("Token-Spar- & FinOps-Ökosystem","Token 节省与 FinOps 生态系统"),
 ("Kostenminimierung","成本最小化"),
 ("Kernel, Scheduling & Daemon-Architektur","内核、调度与守护进程架构"),
 ("Multi-Agenten-Prozessmodell, Hierarchie & Synthese","多智能体流程模型、层级与综合"),
 ("MCP-Treiber, Externe Dienste & Multimodale Werkzeuge","MCP 驱动、外部服务与多模态工具"),
 ("Gedächtnis, Datenbank-Hygiene & Obsidian 2nd Brain","记忆、数据库卫生与 Obsidian 第二大脑"),
 ("Sicherheit, Zero-Trust Governance & System-Diagnose","安全、零信任治理与系统诊断"),
 ("Selbst-Evolution, Marktplätze & Auto-Dokumentation","自进化、市场与自动文档"),
 ("Referenz-Matrix: Steuerbare Evey/Hermes-Plugins","参考矩阵：可控的 Evey/Hermes 插件"),
 ("Enterprise- & Resilienz-Architektur","企业与弹性架构"),
 ("Autonomie-, Sandbox- & Governance-Architektur","自主、沙箱与治理架构"),
 ("Performance-Core, Durchsatz-Skalierung & Token-Effizienz","性能核心、吞吐扩展与 Token 效率"),
 ("Moderne Gedächtnis- & RAG-Architektur","现代记忆与 RAG 架构"),
 ("Zuverlässige Ausführung & Determinismus","可靠执行与确定性"),
 ("Durable Execution","持久执行"),
 ("Sicherheit, Datenschutz & Enterprise-Guardrails","安全、数据保护与企业护栏"),
 ("Selbst-Optimierung, Evaluation & Schwarm-Intelligenz","自优化、评估与群体智能"),
 ("Wirtschaft & ERP","经济与 ERP"),
 ("Mandanten-Suite","多租户套件"),
 ("Architektur-, Security- & Deployment-Features","架构、安全与部署特性"),
 ("Übersicht: Decision Engine & 6-Phasen-Deliberation","概述：Decision Engine 与六阶段审议"),
 ("Agile, Lean & Innovation","敏捷、精益与创新"),
 ("Ursachenanalyse & Formale Logik","根因分析与形式逻辑"),
 ("Kognitive Entzerrung & Debatte","认知去偏与辩论"),
 ("Strategie, Moat & Positionierung","战略、护城河与定位"),
 ("Marktanalyse, Nachfrage & Spieltheorie","市场分析、需求与博弈论"),
 ("Product-Launch & Growth Engineering","产品发布与增长工程"),
 ("Business Model & Venture Building","商业模式与创业构建"),
 ("Operations, Durchsatz & Qualität","运营、吞吐与质量"),
 ("Systemdenken, Risiko & Resilienz","系统思维、风险与韧性"),
 ("Was ist Archon OS und wie arbeitet man damit?","什么是 Archon OS 以及如何使用它？"),
 ("Die vier System-Säulen von Archon OS im Überblick:","Archon OS 四大系统支柱概览："),
 ("Wie liest man dieses Handbuch?","如何阅读本手册？"),
 ("Installationshinweise","安装说明"),
 ("Systemvoraussetzungen","系统要求"),
 ("Interaktive 1-Click-Installation","交互式一键安装"),
 ("Agenten-Installation, täglicher Betrieb & Sicherheit","智能体安装、日常运行与安全"),
 ("Installation unter Linux & macOS","在 Linux 与 macOS 下的安装"),
 ("Operative Projektsteuerung & Funk","运营项目控制与通信"),
 ("Posteingang & Ereignis-Stream","收件箱与事件流"),
 ("Agenten-Kader","智能体团队"),
 ("Fähigkeiten & Autonomie-Engines","能力与自主引擎"),
 ("Der vollständige Flotten-Kader: Alle 70 Spezialisten nach Fachdomänen","完整舰队名册：按专业领域的 70 名专家"),
 ("Zentralbibliothek","中央图书馆"),
 ("Lokales Privacy-Routing","本地隐私路由"),
 ("Zero-Egress Privacy Routing","零外发隐私路由"),
 ("Operative Steuerung","运营控制"),
 ("Kognition & Wissen","认知与知识"),
 ("Infrastruktur & Governance","基础设施与治理"),
 ("4-Augen Qualitäts-Gate & Revisor-Freigabe","四眼质量门与审计员批准"),
 ("Bot Screen (Desktop & Web-Navigator)","Bot Screen（桌面与网页导航器）"),
 ("n8n Automatisierung","n8n 自动化"),
 ("Stichwortverzeichnis","索引"),
 ("Framework-Verzeichnis","框架索引"),
 ("Frameworks","框架"),
 ("Kategorie","类别"),
 ("Zusammenfassung","总结"),
 ("Einführung","引言"),
 ("Vorwort","前言"),
 ("Anhang","附录"),
 ("Grundlagen","基础"),
 ("Ansicht","视图"),
 ("Berechtigung","权限"),
 ("Berechtigungen","权限"),
 ("Benutzer","用户"),
 ("Mandant","租户"),
 ("Mandanten","租户"),
 ("Sicherung","备份"),
 ("Wiederherstellung","恢复"),
 ("Überwachung","监控"),
 ("Protokoll","日志"),
 ("Protokolle","日志"),
 ("Datenbank","数据库"),
 ("Speicher","存储"),
 ("Netzwerk","网络"),
 ("Server","服务器"),
 ("Client","客户端"),
 ("Anwendung","应用"),
 ("Anwendungen","应用"),
 ("Einstellung","设置"),
 ("Einstellungen","设置"),
 ("Konfiguration","配置"),
 ("Installation","安装"),
 ("Aktualisierung","更新"),
 ("Version","版本"),
 ("Funktion","功能"),
 ("Funktionen","功能"),
 ("Leistung","性能"),
 ("Zuverlässigkeit","可靠性"),
 ("Verfügbarkeit","可用性"),
 ("Skalierung","扩展"),
 ("Automatisierung","自动化"),
 ("Integration","集成"),
 ("Schnittstelle","接口"),
 ("Arbeitsablauf","工作流"),
 ("Aufgabe","任务"),
 ("Aufgaben","任务"),
 ("Projekt","项目"),
 ("Projekte","项目"),
 ("Team","团队"),
 ("Rolle","角色"),
 ("Rollen","角色"),
 ("Zugriff","访问"),
 ("Authentifizierung","身份验证"),
 ("Autorisierung","授权"),
 ("Verschlüsselung","加密"),
 ("Schlüssel","密钥"),
 ("Zertifikat","证书"),
 ("Fehler","错误"),
 ("Warnung","警告"),
 ("Hinweis","说明"),
 ("Beispiel","示例"),
 ("Schritt","步骤"),
 ("Schritte","步骤"),
 ("Anleitung","指南"),
 ("Handbuch","手册"),
 ("Dokumentation","文档"),
 ("Entwicklung","开发"),
 ("Betrieb","运行"),
 ("Wartung","维护"),
 ("Test","测试"),
 ("Tests","测试"),
 ("Qualität","质量"),
 ("Risiko","风险"),
 ("Bedrohung","威胁"),
 ("Angriff","攻击"),
 ("Schutz","保护"),
 ("Privatsphäre","隐私"),
 ("Datenschutz","数据保护"),
 ("Einwilligung","同意"),
 ("Richtlinie","策略"),
 ("Prozess","流程"),
 ("Prozesse","流程"),
 ("Strategie","战略"),
 ("Entscheidung","决策"),
 ("Entscheidungen","决策"),
 ("Analyse","分析"),
 ("Bewertung","评估"),
 ("Bericht","报告"),
 ("Berichte","报告"),
 ("Dashboard","仪表板"),
 ("Diagramm","图表"),
 ("Tabelle","表格"),
 ("Abbildung","图"),
 ("Seite","页"),
 ("Kapitel","章"),
 ("Abschnitt","节"),
 ("Verzeichnis","目录"),
 ("Suche","搜索"),
 ("Filter","筛选"),
 ("Sortierung","排序"),
 ("Import","导入"),
 ("Export","导出"),
 ("Synchronisierung","同步"),
 ("Verbindung","连接"),
 ("Ereignis","事件"),
 ("Ereignisse","事件"),
 ("Nachricht","消息"),
 ("Nachrichten","消息"),
 ("E-Mail","电子邮件"),
 ("Messenger","即时消息"),
 ("Freigabe","批准"),
 ("Freigaben","批准"),
 ("Genehmigung","审批"),
 ("Steuerung","控制"),
 ("Regelung","调节"),
 ("Planung","规划"),
 ("Umsetzung","实施"),
 ("Optimierung","优化"),
 ("Effizienz","效率"),
 ("Kosten","成本"),
 ("Nutzen","收益"),
 ("Wert","价值"),
 ("Kunde","客户"),
 ("Kunden","客户"),
 ("Lieferant","供应商"),
 ("Vertrag","合同"),
 ("Rechnung","发票"),
 ("Zahlung","付款"),
 ("Steuer","税"),
 ("Steuern","税务"),
 ("Recht","法律"),
 ("Gesetz","法规"),
 ("Compliance","合规"),
 ("Wissen","知识"),
 ("Gedächtnis","记忆"),
 ("Lernen","学习"),
 ("Modell","模型"),
 ("Modelle","模型"),
 ("Agent","智能体"),
 ("Agenten","智能体"),
 ("Assistent","助手"),
 ("Chat","聊天"),
 ("Dialog","对话"),
 ("Antwort","回答"),
 ("Frage","问题"),
 ("Eingabe","输入"),
 ("Ausgabe","输出"),
 ("Ergebnis","结果"),
 ("Ergebnisse","结果"),
 ("Quelle","来源"),
 ("Quellen","来源"),
 ("Ziel","目标"),
 ("Start","开始"),
 ("Ende","结束"),
 ("Status","状态"),
 ("Aktiv","活动"),
 ("Inaktiv","非活动"),
 ("Neu","新建"),
 ("Bearbeiten","编辑"),
 ("Löschen","删除"),
 ("Speichern","保存"),
 ("Öffnen","打开"),
 ("Schließen","关闭"),
 ("Erstellen","创建"),
 ("Hinzufügen","添加"),
 ("Entfernen","移除"),
 ("Aktualisieren","刷新"),
 ("Abbrechen","取消"),
 ("Bestätigen","确认"),
 ("Ausführen","执行"),
 ("Ausführung","执行"),
 ("Starten","启动"),
 ("Stoppen","停止"),
 ("Pausieren","暂停"),
 ("Fortsetzen","继续"),
 ("Zurück","返回"),
 ("Weiter","下一步"),
 ("Fertig","完成"),
 ("Übersicht","概述"),
 ("Details","详情"),
 ("Beschreibung","描述"),
 ("Name","名称"),
 ("Titel","标题"),
 ("Datum","日期"),
 ("Zeit","时间"),
 ("Dauer","持续时间"),
 ("Priorität","优先级"),
 ("Kritisch","严重"),
 ("Hoch","高"),
 ("Mittel","中"),
 ("Niedrig","低"),
 ("Öffentlich","公开"),
 ("Privat","私有"),
 ("Intern","内部"),
 ("Extern","外部"),
 ("Deutsch","德语"),
 ("Englisch","英语"),
 ("Sprache","语言"),
 ("Benutzeroberfläche","用户界面"),
 ("Hilfe","帮助"),
 ("Unterstützung","支持"),
 ("Fehlerbehebung","故障排除"),
 ("Werkzeug","工具"),
 ("Werkzeuge","工具"),
 ("Dienst","服务"),
 ("Dienste","服务"),
 ("Plattform","平台"),
 ("Infrastruktur","基础设施"),
 ("Architektur","架构"),
 ("Komponente","组件"),
 ("Modul","模块"),
 ("Plugin","插件"),
 ("Erweiterung","扩展"),
 ("Vorlage","模板"),
 ("Vorlagen","模板"),
 ("Workflow","工作流"),
 ("Aufgabenliste","任务列表"),
 ("Kalender","日历"),
 ("Datei","文件"),
 ("Dateien","文件"),
 ("Ordner","文件夹"),
 ("Bild","图像"),
 ("Video","视频"),
 ("Audio","音频"),
 ("Text","文本"),
 ("Link","链接"),
 ("URL","URL"),
 ("Pfad","路径"),
 ("Parameter","参数"),
 ("Option","选项"),
 ("Optionen","选项"),
 ("Standard","默认"),
 ("Benutzerdefiniert","自定义"),
 ("Erweitert","高级"),
 ("Einfach","简单"),
 ("Schnell","快速"),
 ("Langsam","缓慢"),
 ("Automatisch","自动"),
 ("Manuell","手动"),
 ("Regelmäßig","定期"),
 ("Täglich","每日"),
 ("Wöchentlich","每周"),
 ("Monatlich","每月"),
 ("Jährlich","每年"),
 ("Heute","今天"),
 ("Gestern","昨天"),
 ("Morgen","明天"),
 ("Jetzt","现在"),
 ("Später","稍后"),
 ("Sofort","立即"),
 ("Bitte","请"),
 ("Danke","谢谢"),
 ("Willkommen","欢迎"),
 ("Abmeldung","注销"),
 ("Anmeldung","登录"),
 ("Kennwort","密码"),
 ("Passwort","密码"),
 ("Konto","账户"),
 ("Profil","个人资料"),
 ("Gruppe","组"),
 ("Organisation","组织"),
 ("Unternehmen","企业"),
 ("Abteilung","部门"),
 ("Mitarbeiter","员工"),
 ("Kostenstelle","成本中心"),
 ("Berichtswesen","报告"),
 ("Kennzahl","指标"),
 ("Metrik","指标"),
 ("Schwellenwert","阈值"),
 ("Alarm","告警"),
 ("Benachrichtigung","通知"),
 ("Eskalation","升级"),
 ("Störung","故障"),
 ("Wartungsfenster","维护窗口"),
 ("Notfall","紧急情况"),
 ("Wiederanlauf","重启"),
 ("Hochverfügbarkeit","高可用性"),
 ("Ausfallsicherheit","容错"),
 ("Lastverteilung","负载均衡"),
 ("Durchsatz","吞吐量"),
 ("Latenz","延迟"),
 ("Antwortzeit","响应时间"),
 ("Ressource","资源"),
 ("Ressourcen","资源"),
 ("Kapazität","容量"),
 ("Auslastung","利用率"),
 ("Kern","内核"),
 ("Prozessor","处理器"),
 ("Arbeitsspeicher","内存"),
 ("Festplatte","磁盘"),
 ("Bandbreite","带宽"),
 ("Knoten","节点"),
 ("Cluster","集群"),
 ("Container","容器"),
 ("Image","镜像"),
 ("Volume","卷"),
 ("Netzwerksegment","网段"),
 ("Firewall","防火墙"),
 ("Proxy","代理"),
 ("Gateway","网关"),
 ("Lastenausgleich","负载均衡"),
 ("Sitzung","会话"),
 ("Token","Token"),
 ("Anfrage","请求"),
 ("Antworten","响应"),
 ("Abfrage","查询"),
 ("Antwortzeit","响应时间"),
 ("Cache","缓存"),
 ("Warteschlange","队列"),
 ("Stapel","批处理"),
 ("Zeitplan","计划"),
 ("Aufgabenplanung","任务调度"),
 ("Hintergrundprozess","后台进程"),
 ("Daemon","守护进程"),
 ("Protokollierung","日志记录"),
 ("Audit","审计"),
 ("Nachverfolgung","跟踪"),
 ("Versionierung","版本控制"),
 ("Änderung","变更"),
 ("Änderungen","变更"),
 ("Freigabeverfahren","发布流程"),
 ("Bereitstellung","部署"),
 ("Umgebung","环境"),
 ("Umgebungen","环境"),
 ("Produktion","生产"),
 ("Staging","预发布"),
 ("Entwicklungsumgebung","开发环境"),
 ("Testumgebung","测试环境"),
 ("Mandantenfähigkeit","多租户能力"),
 ("Isolation","隔离"),
 ("Sandbox","沙箱"),
 ("Eingabevalidierung","输入验证"),
 ("Ausgabevalidierung","输出验证"),
 ("Rollenbasiert","基于角色的"),
 ("Zugriffskontrolle","访问控制"),
 ("Identität","身份"),
 ("Verzeichnisdienst","目录服务"),
 ("Einmalanmeldung","单点登录"),
 ("Mehrfaktorauthentifizierung","多因素身份验证"),
 ("Sitzungsverwaltung","会话管理"),
 ("Schlüsselmanagement","密钥管理"),
 ("Geheimnis","机密"),
 ("Geheimnisse","机密"),
 ("Tresor","保管库"),
 ("Sicherheitsüberprüfung","安全检查"),
 ("Schwachstelle","漏洞"),
 ("Schwachstellen","漏洞"),
 ("Patch","补丁"),
 ("Update","更新"),
 ("Upgrade","升级"),
 ("Migration","迁移"),
 ("Backup","备份"),
 ("Wiederherstellungspunkt","恢复点"),
 ("Notfallplan","应急计划"),
 ("Geschäftskontinuität","业务连续性"),
 ("Risikomanagement","风险管理"),
 ("Bedrohungsmodell","威胁模型"),
 ("Angriffsfläche","攻击面"),
 ("Vertraulichkeit","机密性"),
 ("Integrität","完整性"),
 ("Verfügbarkeitsziel","可用性目标"),
 ("Service-Level","服务水平"),
 ("Vereinbarung","协议"),
 ("Anforderung","需求"),
 ("Anforderungen","需求"),
 ("Spezifikation","规范"),
 ("Entwurf","设计"),
 ("Implementierung","实现"),
 ("Validierung","验证"),
 ("Verifizierung","核查"),
 ("Abnahme","验收"),
 ("Rollout","推广"),
 ("Schulung","培训"),
 ("Support","支持"),
 ("Dokumentationspflicht","文档义务"),
 ("Nachweispflicht","举证义务"),
 ("Aufbewahrung","归档"),
 ("Löschkonzept","删除方案"),
 ("Auftragsverarbeitung","委托处理"),
 ("Betroffenenrechte","数据主体权利"),
 ("Auskunft","信息公开"),
 ("Berichtigung","更正"),
 ("Löschung","删除"),
 ("Einschränkung","限制"),
 ("Übertragbarkeit","可携带性"),
 ("Widerspruch","反对"),
 ("Folgenabschätzung","影响评估"),
 ("Verarbeitungsverzeichnis","处理活动记录"),
 ("Technische Maßnahmen","技术措施"),
 ("Organisatorische Maßnahmen","组织措施"),
 ("Auftragnehmer","受托方"),
 ("Dienstleister","服务商"),
 ("Subunternehmer","分包商"),
 ("Vertraulichkeitserklärung","保密声明"),
 ("Geheimhaltungsvereinbarung","保密协议"),
 ("Rahmenvertrag","框架合同"),
 ("Einzelvertrag","单项合同"),
 ("Leistungsbeschreibung","服务描述"),
 ("Abrechnung","结算"),
 ("Gutschrift","贷记"),
 ("Mahnwesen","催款"),
 ("Zahlungsbedingung","付款条件"),
 ("Lieferbedingung","交货条件"),
 ("Gewährleistung","质保"),
 ("Haftung","责任"),
 ("Garantie","担保"),
 ("Versicherung","保险"),
 ("Steuernummer","税号"),
 ("Umsatzsteuer","增值税"),
 ("Einkommensteuer","所得税"),
 ("Körperschaftsteuer","企业所得税"),
 ("Buchhaltung","会计"),
 ("Bilanz","资产负债表"),
 ("Gewinn","利润"),
 ("Verlust","亏损"),
 ("Umsatz","营业额"),
 ("Aufwand","费用"),
 ("Ertrag","收益"),
 ("Budget","预算"),
 ("Forecast","预测"),
 ("Kennzahlen","关键指标"),
 ("Wachstum","增长"),
 ("Innovation","创新"),
 ("Agilität","敏捷"),
 ("Resilienz","韧性"),
 ("Nachhaltigkeit","可持续性"),
 ("Effektivität","有效性"),
 ("Transparenz","透明度"),
 ("Fairness","公平性"),
 ("Verantwortung","责任"),
 ("Entscheidungsfindung","决策制定"),
 ("Beratung","咨询"),
 ("Moderation","主持"),
 ("Abstimmung","表决"),
 ("Konsens","共识"),
 ("Mehrheit","多数"),
 ("Veto","否决"),
 ("Szenario","情景"),
 ("Szenarien","情景"),
 ("Prognose","预测"),
 ("Trend","趋势"),
 ("Markt","市场"),
 ("Wettbewerb","竞争"),
 ("Wettbewerber","竞争对手"),
 ("Alleinstellungsmerkmal","独特卖点"),
 ("Zielgruppe","目标群体"),
 ("Segment","细分"),
 ("Positionierung","定位"),
 ("Preisgestaltung","定价"),
 ("Vertrieb","销售"),
 ("Marketing","营销"),
 ("Kampagne","活动"),
 ("Kanal","渠道"),
 ("Partner","合作伙伴"),
 ("Lieferkette","供应链"),
 ("Beschaffung","采购"),
 ("Bestand","库存"),
 ("Logistik","物流"),
 ("Produktion","生产"),
 ("Fertigung","制造"),
 ("Qualitätssicherung","质量保证"),
 ("Prüfung","检验"),
 ("Messung","测量"),
 ("Kennlinie","特性曲线"),
 ("Fehlerrate","故障率"),
 ("Ausschuss","废品"),
 ("Nacharbeit","返工"),
 ("Reklamation","投诉"),
 ("Kundenzufriedenheit","客户满意度"),
 ("Feedback","反馈"),
 ("Verbesserung","改进"),
 ("Kontinuierlich","持续"),
 ("Methode","方法"),
 ("Methoden","方法"),
 ("Werkstatt","车间"),
 ("Fabrik","工厂"),
 ("Anlage","设备"),
 ("Maschine","机器"),
 ("Wartungsplan","维护计划"),
 ("Ersatzteil","备件"),
 ("Störungsmeldung","故障报告"),
 ("Entstörung","排障"),
 ("Inbetriebnahme","投运"),
 ("Abnahmeprotokoll","验收记录"),
 ("Betriebsanleitung","操作手册"),
 ("Sicherheitsdatenblatt","安全数据表"),
 ("Gefährdungsbeurteilung","危险评估"),
 ("Arbeitsschutz","劳动保护"),
 ("Unterweisung","指导"),
 ("Zertifizierung","认证"),
 ("Norm","标准"),
 ("Standardvorgehen","标准程序"),
 ("Arbeitsanweisung","作业指导"),
 ("Checkliste","检查表"),
 ("Formular","表单"),
 ("Antrag","申请"),
 ("Bewilligung","批准"),
 ("Ablehnung","拒绝"),
 ("Rückmeldung","反馈"),
 ("Stellungnahme","意见"),
 ("Gutachten","鉴定"),
 ("Prüfbericht","检验报告"),
 ("Auditbericht","审计报告"),
 ("Maßnahme","措施"),
 ("Maßnahmen","措施"),
 ("Frist","期限"),
 ("Termin","日期"),
 ("Meilenstein","里程碑"),
 ("Zeitplanabweichung","进度偏差"),
 ("Kostenabweichung","成本偏差"),
 ("Leistungsumfang","工作范围"),
 ("Lastenheft","需求说明书"),
 ("Pflichtenheft","功能说明书"),
 ("Angebot","报价"),
 ("Auftrag","订单"),
 ("Bestellung","订购"),
 ("Lieferung","交付"),
 ("Abnahme","验收"),
 ("Rechnungsstellung","开票"),
 ("Zahlungseingang","收款"),
 ("Offene Posten","未清项"),
 ("Mahnstufe","催款等级"),
 ("Inkasso","托收"),
 ("Bonität","信用"),
 ("Kreditlimit","信用额度"),
 ("Vorkasse","预付款"),
 ("Teilzahlung","分期付款"),
 ("Ratenzahlung","分期付款"),
 ("Skonto","现金折扣"),
 ("Rabatt","折扣"),
 ("Bonus","奖金"),
 ("Provision","佣金"),
 ("Gehalt","工资"),
 ("Lohn","薪酬"),
 ("Arbeitszeit","工时"),
 ("Überstunde","加班"),
 ("Urlaub","休假"),
 ("Krankheit","病假"),
 ("Einstellung","招聘"),
 ("Kündigung","解雇"),
 ("Arbeitsvertrag","劳动合同"),
 ("Stellenbeschreibung","职位描述"),
 ("Bewerbung","求职申请"),
 ("Vorstellungsgespräch","面试"),
 ("Einarbeitung","入职培训"),
 ("Weiterbildung","继续教育"),
 ("Schulungsplan","培训计划"),
 ("Kompetenz","能力"),
 ("Kompetenzen","能力"),
 ("Fähigkeit","能力"),
 ("Fähigkeiten","能力"),
 ("Erfahrung","经验"),
 ("Kenntnis","知识"),
 ("Kenntnisse","知识"),
 ("Qualifikation","资质"),
 ("Zertifikat","证书"),
 ("Nachweis","证明"),
 ("Befugnis","授权"),
 ("Vollmacht","全权委托"),
 ("Unterschrift","签名"),
 ("Datum der Ausstellung","签发日期"),
 ("Gültigkeit","有效期"),
 ("Ablaufdatum","到期日"),
 ("Verlängerung","延期"),
 ("Kündigungsschreiben","解约函"),
 ("Vertragsstrafe","合同违约金"),
 ("Schadensersatz","损害赔偿"),
 ("Gerichtsstand","管辖法院"),
 ("Schiedsverfahren","仲裁"),
 ("Mediation","调解"),
 ("Klage","诉讼"),
 ("Urteil","判决"),
 ("Rechtsmittel","法律救济"),
 ("Fristsetzung","设定期限"),
 ("Verzug","迟延"),
 ("Rücktritt","解除"),
 ("Widerruf","撤销"),
 ("Anfechtung","异议"),
 ("Nichtigkeit","无效"),
 ("Wirksamkeit","效力"),
 ("Bestandteil","组成部分"),
 ("Anlage zum Vertrag","合同附件"),
 ("Vertragsbeginn","合同开始"),
 ("Vertragsende","合同结束"),
 ("Laufzeit","期限"),
 ("Verlängerungsoption","续约选择权"),
 ("Kündigungsfrist","解约通知期"),
]

WORD_MAP = [
 ("Inhaltsverzeichnis","目录"),("Inhalt","目录"),
 ("Abb.","图"),
 ("Hinweise","说明"),("Voraussetzungen","前提条件"),
 ("Betrieb","运行"),("Sicherheit","安全"),
 ("Übersicht","概述"),("Detail","详情"),
 ("Ansicht","视图"),("Ansichten","视图"),
 ("Ereignis","事件"),("Protokoll","日志"),
]

def protect(s):
    reps = []
    def sub_pat(pat, s):
        def rpl(m):
            reps.append(m.group(0)); return "\uE000%d\uE001" % (len(reps)-1)
        return re.sub(pat, rpl, s)
    s = sub_pat(r"https?://[^\s\)\"']+", s)
    s = sub_pat(r"[A-Za-z]:[\\/][^\s]*|/[A-Za-z0-9_\-\.\/]{3,}|[a-z_]+(?:/[a-z0-9_\-\.]+)+", s)
    s = sub_pat(r"\b[A-Z_][A-Z0-9_]{2,}\b", s)
    s = sub_pat(r"\b[a-z_]+(?:\.[a-z_]+)+\b", s)
    s = sub_pat(r"\b(?:--?[a-z][\w\-]*|/[a-z]+)\b(?=\s|$)", s)
    s = sub_pat(r":\d{2,5}\b", s)
    for term in sorted(LOCKS, key=len, reverse=True):
        if term in s:
            idx = len(reps); reps.append(term)
            s = s.replace(term, "\uE000%d\uE001" % idx)
    return s, reps

def restore(s, reps):
    def rpl(m):
        return reps[int(m.group(1))]
    return re.sub("\uE000(\\d+)\uE001", rpl, s)

def offline_translate(txt):
    s, reps = protect(txt)
    # Abb. 12: -> 图 12:
    s = re.sub(r"\bAbb\.\s*(\d+)\s*:", r"图 \1:", s)
    s = s.replace("Abb.", "图")
    for de, zh in PHRASE_MAP:
        if de in s:
            s = s.replace(de, zh)
    # Zahlen in Klammern wie (v0.5.1) bleiben durch protect; simple plural fixes
    for de, zh in WORD_MAP:
        if de in s:
            s = s.replace(de, zh)
    # generische deutsche Funktionswoerter -> Chinesisch (vorsichtig)
    func = [
     (" und "," 与 "),(" oder "," 或 "),(" mit "," 与 "),(" ohne "," 无 "),
     (" für "," 针对 "),(" von "," 的 "),(" der "," "),(" die "," "),(" das "," "),
     (" im "," 在 "),(" in "," 在 "),(" am "," 在 "),(" zum "," 至 "),
     (" zur "," 至 "),(" beim "," 在 "),(" durch "," 通过 "),(" über "," 关于 "),
     (" unter "," 在…下 "),(" zwischen "," 之间 "),(" innerhalb "," 之内 "),
     (" außerhalb "," 之外 "),(" nach "," 在…之后 "),(" vor "," 在…之前 "),
     (" bei "," 在 "),(" ist "," 是 "),(" sind "," 是 "),(" wird "," 将 "),
     (" werden "," 将 "),(" kann "," 可 "),(" können "," 可 "),(" muss "," 须 "),
     (" müssen "," 须 "),(" soll "," 应 "),(" sollten "," 应 "),(" nicht "," 不 "),
     (" keine "," 无 "),(" keine "," 无 "),(" alle "," 所有 "),(" jede "," 每 "),
     (" jedes "," 每 "),(" jeder "," 每 "),(" diese "," 本 "),(" dieser "," 本 "),
     (" dieses "," 本 "),(" als "," 作为 "),(" wie "," 如 "),(" auch "," 也 "),
     (" nur "," 仅 "),(" bereits "," 已 "),(" noch "," 仍 "),(" schon "," 已 "),
     (" sehr "," 很 "),(" mehr "," 更多 "),(" weniger "," 更少 "),(" neu "," 新 "),
     (" automatisch "," 自动 "),(" manuell "," 手动 "),
    ]
    for de, zh in func:
        if de in s:
            s = s.replace(de, zh)
    s = restore(s, reps)
    # (DE) -> (ZH) handled globally, but also here
    s = s.replace("(DE)", "(ZH)")
    return s

def process_one(src, dst):
    doc = docx.Document(src)
    body = doc._body._body
    toc_ps = {p_el for sdt in body.findall("w:sdt", NS) for p_el in sdt.findall(".//w:p", NS)}
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    targets, pending, seen = [], [], set()
    for p_el in body.iter():
        if p_el.tag.endswith("}p") and p_el not in toc_ps:
            merge_adjacent_similar_runs(p_el)
            for r_el in p_el.findall("w:r", NS):
                if r_el.find("w:drawing", NS) is not None or r_el.find("w:fldChar", NS) is not None:
                    continue
                t_els = r_el.findall("w:t", NS)
                if not t_els:
                    continue
                txt = "".join(t.text or "" for t in t_els)
                if should_skip_text(txt):
                    continue
                targets.append((r_el, t_els, txt))
                if txt not in cache and txt not in seen:
                    seen.add(txt); pending.append(txt)
    print(f"{src}: Segmente gesamt {len(targets)}, unuebersetzt {len(pending)}", flush=True)
    # Batches ~18
    done = 0
    batch = []
    def flush_batch(batch):
        for s_src in batch:
            cache[s_src] = offline_translate(s_src)
        with open(CACHE, "w", encoding="utf-8") as cf:
            json.dump(cache, cf, ensure_ascii=False, indent=1)
    for t in pending:
        batch.append(t)
        if len(batch) >= BATCH:
            flush_batch(batch); done += len(batch)
            print(f"  batch {done}/{len(pending)}", flush=True)
            batch = []
    if batch:
        flush_batch(batch); done += len(batch)
        print(f"  batch {done}/{len(pending)} fertig", flush=True)
    for r_el, t_els, txt in targets:
        tr = cache.get(txt, txt)
        if txt.startswith(" ") and not tr.startswith(" "):
            tr = " " + tr
        if txt.endswith(" ") and not tr.endswith(" "):
            tr = tr + " "
        t_els[0].set(qn("w:space"), "preserve")
        t_els[0].text = tr
        for extra in t_els[1:]:
            r_el.remove(extra)
    for sdt in body.findall("w:sdt", NS):
        for t in sdt.findall(".//w:t", NS):
            if t.text and t.text.strip() in ("Inhalt", "Table of Contents"):
                t.text = TOC_TITLE
    for el in body.iter():
        if el.tag.endswith("}lang"):
            el.set(qn("w:val"), LOCALE)
        elif el.tag.endswith("}t") and el.text and "(DE)" in el.text:
            el.text = el.text.replace("(DE)", f"({TAG})")
    if doc.tables:
        last_tbl = doc.tables[-1]
        trs = last_tbl._tbl.findall("w:tr", NS)
        if len(trs) > 2:
            data_trs = trs[1:]
            srt = sorted(data_trs, key=lambda tr_el: "".join(t.text or "" for t in tr_el.findall("w:tc", NS)[0].findall(".//w:t", NS)).strip().lower())
            for r in data_trs:
                last_tbl._tbl.remove(r)
            for idx, r in enumerate(srt):
                for tc in r.findall("w:tc", NS):
                    tcPr = tc.find("w:tcPr", NS)
                    if tcPr is not None:
                        old = tcPr.find("w:shd", NS)
                        if old is not None:
                            tcPr.remove(old)
                        if idx % 2 == 1:
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), "F8FAFC")
                            tcPr.append(shd)
                last_tbl._tbl.append(r)
    doc.save(dst)
    print(f"Gespeichert: {dst}", flush=True)
    return len(targets)

if __name__ == "__main__":
    jobs = [
     ("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx", "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_ZH.docx"),
     ("docs/system/ARCHON_OS_FEATURELISTE_2026.docx", "docs/system/ARCHON_OS_FEATURELISTE_2026_ZH.docx"),
     ("docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_ZH.docx" if False else "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.docx", "docs/system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_ZH.docx"),
    ]
    counts = {}
    for src, dst in jobs:
        counts[dst] = process_one(src, dst)
    # Word-COM Export
    for _, dst in jobs:
        pdf = os.path.splitext(dst)[0] + ".pdf"
        print(f"Word-Export: {dst} -> {pdf}", flush=True)
        export_pdf_and_update_glossary_windows(dst, pdf, PREFIX)
        print(f"PDF: {pdf} ({os.path.getsize(pdf)/1024/1024:.2f} MB)", flush=True)
    print(json.dumps(counts, ensure_ascii=False))
