# yichen-skills

[English](./README.md) | [中文](./README.zh.md) | Türkçe

Claude Code ve Codex ile yazım, X içerik dilimleme, X Articles taslak yayımlama, WeChat dijital varlık yakalama ve yerel iş akışlarını kolaylaştırmak isteyen içerik üreticileri için hazırlanmış bir beceri (skill) koleksiyonu.

## Geliştirici

2006 doğumlu seri girişimci, hukuk öğrencisi ve Yu Hackathon (渝客松) kurucusu **逸尘 (Yichen)** tarafından geliştirilmekte ve sürdürülmektedir; işletmeler için yapay zekâ ürünleri, içerik ve hizmetler üzerine çalışmaktadır.

- Kişisel web sitesi: [yichen.ai](https://yichen.ai/) · [Hakkımda](https://yichen.ai/about/)
- Sosyal medya: [X](https://x.com/gengdaJ) · [YouTube](https://www.youtube.com/@yichenai) · [Douyin](https://v.douyin.com/diF63UgPZtI) · [Xiaohongshu](https://xhslink.com/m/3eiF47bau17)
- WeChat: `yichen10801`; yedek: `yichen365ai`
- Eklerken lütfen doğrulama mesajına `GitHub` yazın

Güncel kişisel bilgiler, ürünler, hizmetler ve iletişim ayrıntıları için [yichen.ai](https://yichen.ai/) adresine bakın.

## Kişisel Kullanım ve Ticari Yetkilendirme

Bu depo yalnızca kişisel öğrenme ve ticari olmayan kişisel kullanım içindir. Müşteri teslimatı, ücretli ürün veya hizmetler, şirket içi kurulum, pazar yeri paketlemesi ve kurs paketleri dahil her türlü ticari kullanım, geliştiricinin önceden açık yazılı iznini gerektirir.

Ticari yetkilendirme talep etmek için WeChat üzerinden `yichen10801` hesabıyla iletişime geçin ve doğrulama mesajına `Commercial Authorization` yazın. İletişim isteği göndermek tek başına izin vermez; ticari kullanıma yalnızca açık yazılı onay aldıktan sonra izin verilir.

Bu depodaki tüm Beceriler için ticari yetkilendirmeyi açmak ve 2005 veya sonrası doğumlu girişimciler ile kanıtlanmış sonuçlara sahip deneyimli uygulayıcılarla bağlantı kurmak için Yichen'in ücretli topluluğu **TradeWinds**'e katılabilirsiniz. Üyelik ücreti için WeChat üzerinden Yichen (`yichen10801`) ile iletişime geçin. Kapsam yazılı yetkilendirmeye tabidir; üçüncü taraf bileşenler kendi orijinal lisanslarına tabi olmaya devam eder.

## Bu Depo Ne Yapar?

1. Obsidian/Markdown makalelerini X Articles taslaklarına yükler (`yichen-x-article-draft-uploader`)
2. Tek bir Mac'te ayırt edici mavi simgeyle iki WeChat hesabını aynı anda çalıştırır (`yichen-mac-wechat-dual-open`)
3. macOS ve Windows'ta yerel WeChat sohbetlerini, Moments paylaşımlarını ve Favorileri dijital varlıklara dönüştürür (`yichen-wechat-local-vault`)
4. Bilinen Douyin bağlantılarından referans videolarını indirir (`yichen-content-archive`)
5. Bilinen Xiaohongshu bağlantılarından referans gönderilerini indirir (`yichen-content-archive`)
6. Dahili Doubao/Volcengine ASR arka ucuyla konuşan kafa videolarına altyazı ekler ve kaba kurgu yapar (`yichen-asr`)
7. Resmî ChatGPT web sayfası üzerinden doğrulanmış araştırma yürütür (`yichen-chatgpt-web-research`)
8. Markdown/Obsidian öncelikli bir Agent Memory Vault sistemini kurar ve sürdürür (`yichen-agent-memory`)
9. WeChat Resmî Hesap makale geçmişini, özgün makale listelerini, gövde metinlerini ve isteğe bağlı okuma/yorum metriklerini toplu dışa aktarır (`yichen-wechat-mp-batch-exporter`)
10. Uygulamayı kontrol etmeden yerel WeCom/企业微信 5.x veritabanı anlık görüntülerini okur ve dışa aktarır (`yichen-wecom-local-vault`)
11. Ana modeli değiştirmeden yerel X araması veya bağımsız ikinci görüş için GPT'nin Grok'u çağırmasını sağlar (`yichen-grok-consult`)
12. Çok aşamalı internet araştırmalarını güvenlik öncelikli tek bir giriş noktasından yönlendirir (`yichen-web-research`)
13. Herkese açık web ve platform aramalarını incelenebilir adaylar hâlinde normalleştirir (`yichen-unified-search`)
14. Yalnızca bilinen veya açıkça onaylanan bağlantıları okur, indirir ve arşivler (`yichen-content-archive`)
15. Mevcut görev yetkilendirmesi altında özel yer imlerini doğrudan dışa aktarır (`yichen-bookmarks-export`)
16. Kayıtlı motor tercihiyle ve yinelenen gönderim olmadan Step, Doubao/Volcengine ve ücretsiz yerel Whisper arasında deşifre yönlendirir (`yichen-asr`)
17. Masaüstü uygulamasını kontrol etmeden resmî CLI üzerinden yetkili WeCom belgeleri oluşturur ve yapılacakları, toplantıları ve takvimleri yönetir (`yichen-wecom-operations`)
18. Herkese açık tek bir X Gönderisi veya Dizisi URL'sini doğrulanmış 3:4 görsel dilimlerine ve yerel videoların tam görüntüsü ile özgün sesini koruyan bitmiş bir videoya dönüştürür (`yichen-x-slicer`)
19. Yalnızca Codex düzenleme ve test yaparken ChatGPT Pro araştırmasını, mimariyi ve salt-okunur proje incelemesini orkestre eder (`codex-chatgpt`)

## Dahil Edilen Beceriler

### `yichen-x-article-draft-uploader`
Obsidian/Markdown uzun makalelerini X Articles taslaklarına yükler:
- İsteğe bağlı 5:2 kapak olarak baştaki görseli kullanır; aksi hâlde taslak kapağını boş bırakır
- Markdown'ı X düzenleyicisi için zengin metne dönüştürür
- Desteklenen boru (pipe) tablolarını yerel X tablo bloklarına dönüştürür
- Orijinal Markdown konumlarına en fazla 25 gövde medya öğesi ekler
- Kullanıcının mevcut Chrome penceresini ele geçirmemek için bağımsız bir Playwright tarayıcısında çalışır
- Chrome oturum durumunu depoya commit etmeden özel bir çerez dosyasına aktarır
- Aynı taslağı yeniden yükler ve metni, tabloları, medya kimliğini, sayısını, sırasını ve konumunu doğrular
- Yalnızca taslak olarak kaydeder ve son `发布` (yayımla) düğmesine asla tıklamaz

Kurulum, gizlilik notları ve sorun giderme için [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md) dosyasına bakın.

### `yichen-mac-wechat-dual-open`
Üçüncü taraf araç olmadan macOS'ta iki WeChat hesabını aynı anda çalıştırır:
- WeChat'i kopyalar, paket tanımlayıcısını (bundle identifier) değiştirir ve yerel olarak yeniden imzalar
- Görsel ayrım için ikinci uygulamanın simgesini yeşilden maviye boyar
- Hem dış hem gömülü simge dosyalarını, Finder özel simgesini ve önbellek yenilemesini yönetir
- Tek komutluk iş akışı: `create` → `recolor-icon` → `launch`
- Tipik tetikleyiciler: "微信双开", "WeChat dual open", "double WeChat"
- Gereksinimler: macOS 12+, `/Applications/WeChat.app` konumunda WeChat, Python 3.10+, Pillow
- Sınırlamalar: WeChat güncellemelerinden sonra bozulur (`repair` komutunu yeniden çalıştırın), anlık bildirimler güvenilir olmayabilir
- [@koffuxu](https://x.com/koffuxu/status/2043110831584690427) tarafından belgelenen kopyalama + bundle-id + ad-hoc imzalama yöntemine dayanır

### `yichen-wechat-local-vault`

**macOS ve Windows'ta birleşik tam yerel WeChat veri ayrıştırma**. Windows tam veritabanı yakalama, kimlik doğrulamalı şifre çözme ve satır satır sohbet ayrıştırma uygulanmıştır; Favoriler ve Moments gövde ayrıştırma da dahili ortak işlev iş akışı üzerinden gerçek veri kabulünden geçmiştir.

- macOS: tam/artımlı şifre çözme, sohbetler, sohbet görselleri/OCR, transferler, Moments, Favoriler, özetler ve cevapsız/yanıt bekleyen kontrolleri
- Windows tam ve artımlı yakalama: `windows capture --scope all --source-id SOURCE_ID` tüm yerel hesap veritabanlarını kapsar; `--mode incremental` en son geçerli anlık görüntüden SHA-256 doğrulamalı değişmemiş veritabanlarını yeni ve değiştirilemez bir anlık görüntüde yeniden kullanır
- Windows Mac-eşdeğeri iş akışları: `snapshot --snapshot <dizin>` artık `validate`, `status`, `sessions`, `unread`, `new-messages`, `chats`, `contacts`, `members`, `history`, `search` (tek sohbet veya `--all` genel), `stats`, `export` (Markdown/TXT), `favorites`, `moments`, `pending`, `transfers`, `digest-source` ve `images` (açık `--attach-dir`, XOR / açık anahtarlı V1/V2 `.dat` çözme) komutlarını sunar
- Windows Favoriler/Moments gövdeleri: doğrudan `snapshot favorites` ve `snapshot moments` üzerinden kullanılabilir (güvenli olmayan `DOCTYPE`/`ENTITY` XML'ini reddeder, salt-okunur, anonim `chat_id` ile)
- Gerçek kabul testleri Windows 11 derleme 26300 ARM64 üzerinde AMD64 WeChat 4.1.15.56 ve CPython 3.12.10 AMD64 ile tam yerel yakalama, sohbet ayrıştırma, Favoriler/Moments gövdeleri, yeni gelen mesajlar ve dışa aktarım geri okumasını kapsar
- Kapsam: seçilen bilgisayara zaten eşitlenmiş veriler. Bilinen üç arama dizini bütünlük boşluğu açıkça raporlanır; Windows 4.x canlı V2 görsel anahtarı otomatik çıkarma, ses/video kurtarma, yönetici olmayan normal çalıştırma, diğer istemci sürümleri/mimarileri ve yeni hizalanan alt komutların gerçek makinede yeniden doğrulanması hâlâ Windows ortamında doğrulama gerektirir
- WeChat arayüzünü kontrol etmez; giriş ve test mesajları kullanıcı tarafından elle yapılır. Windows anahtarları bellekte kalır; düz metin anlık görüntüler özel yerel depolamada tutulur
- Mac bağımlılıkları: Python 3.9+, `pycryptodome`, `zstandard`; Windows CPython 3.12 AMD64, yerel Windows CNG ve sabitlenmiş `zstandard` bağımlılığını kullanır
- Bkz. [Beceri README](./yichen-wechat-local-vault/README.md), [Windows tam yerel ayrıştırma kılavuzu](./yichen-wechat-local-vault/references/windows-live.md) ve [çevrimdışı anlık görüntü kılavuzu](./yichen-wechat-local-vault/references/windows-snapshot.md)

### `yichen-content-archive` içine entegre edilen sosyal medya toplayıcıları
Eski bağımsız Douyin ve Xiaohongshu toplayıcıları artık tek bir doğruluk kaynağında birleştirilmiştir:
- `douyin_download.py` Playwright yakalamasıyla bilinen bir Douyin videosunun meta verilerini okur veya videoyu indirir
- `xiaohongshu_fetch.py` önce bilinen gönderileri anonim olarak okur, ardından istenen video, altyazı veya görselleri indirir
- Mevcut çıktıların üzerine asla yazılmaz; bunun yerine yeni bir `-run-N` yolu seçilir
- Yalnızca not/video ayrıntı bağlantıları kabul edilir; yarıda kesilen indirmeler `.part` adıyla kalır ve sıfır dışı çıkış kodu döndürür, meta veriler ise `xsec_token` veya imzalı medya parametreleri olmadan kanonik bağlantıları saklar
- Xiaohongshu çerezleri açık mevcut-görev yetkilendirmesi gerektirir, yalnızca `xiaohongshu.com` sunucularına gönderilir ve isteğe bağlı Feishu aktarımı açık onay gerektirir

### `yichen-chatgpt-web-research`
Kullanıcının halihazırda oturum açmış resmî ChatGPT web sitesi hesabı için eski salt-araştırma girişi:
- OpenAI API'si veya ayrı bir hesap yerine gerçek ChatGPT web sayfasını kullanır
- Chrome uzantı kontrolünü tercih eder ve yalnızca gerektiğinde görünür Computer Use'a geri döner
- Çıkarma öncesinde benzersiz bir işaretçiyle tam yanıtı bekler
- Ham ve okunabilir Markdown raporlarını mevcut çalışma alanının `reports/` dizinine kaydeder
- Profil adlarını, yerel yolları, çerezleri, belirteçleri ve tarayıcı depolamasını herkese açık becerinin dışında tutar

Gizlilik notları ve iş akışı ayrıntıları için [yichen-chatgpt-web-research/README.md](./yichen-chatgpt-web-research/README.md) dosyasına bakın.

### Birleşik giriş: `codex-chatgpt`
Sınırlı bir Codex × ChatGPT İnceleme Döngüsü çalıştırır:
- ChatGPT Pro herkese açık web araştırması, mimari, PLAN ve son İNCELEME (REVIEW) adımlarını yapar
- Codex tek yerel dosya yazıcısı ve komut/test çalıştırıcısıdır
- Kod, hibrit ve inceleme kipleri ayrı olarak yapılandırılmış bir Secure Tunnel ve yedi araçlı salt-okunur MCP gerektirir
- Saf araştırma kod Tünelini asla başlatmaz veya bağlamaz
- Herkese açık paket hiçbir Runtime Key, Tunnel/App ID, özel çalışma zamanı, tarayıcı oturumu, ekran görüntüsü veya kişisel mutlak yol içermez

Bu, birleşik araştırma + mimari + inceleme girişidir. Eski `yichen-chatgpt-web-research` dizini salt-araştırma iş akışı olarak kalmaya devam eder. Kurulum ve harici çalışma zamanı sözleşmesi için [codex-chatgpt/README.md](./yichen-codex-chatgpt/README.md) dosyasına bakın.

### `yichen-agent-memory`
Herkese açık Agent Memory Vault sistemini kurar ve sürdürür:
- Herkese açık şablondan yerel, Markdown/Obsidian öncelikli bir bellek kasası oluşturur
- Doğruluk kaynağı olarak Markdown'ı, hızlı dizin olarak SQLite/FTS'yi kullanır
- Bulanık "anlam tabanlı" hatırlama için isteğe bağlı Zvec anlamsal getirmeyi destekler
- Yazma öncesi uzlaştırma, kapanış, denetim ve gizlilik dostu şablon güncellemelerine rehberlik eder
- Tipik tetikleyiciler: "install Agent Memory Vault", "set up memory vault", "run memory closeout", "audit my Agent Memory Vault"
- Şablon deposu: [mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault)

### `yichen-wechat-mp-batch-exporter`
WeChat Resmî Hesap makalelerini toplu dışa aktarır:
- Bilinen `mp.weixin.qq.com` makale URL'lerini Markdown/JSON/metin/HTML olarak indirir
- Hesap araması ve geçmiş listesi eşitlemesi için `wechat-article-exporter` kullanır
- `publish_groups`, `expanded_url_items` ve `original_articles` yapılarını ayırır
- Güncel kullanıcı kimlik bilgileri mevcut olduğunda `wxdown-service` üzerinden okuma sayıları, beğeniler, paylaşımlar, yorumlar ve yanıtlar için gelişmiş arşiv planlamasını destekler
- QR girişi, kimlik bilgisi yakalama, sertifika güveni, vekil sunucu değişiklikleri ve tüm WeChat masaüstü adımları için kullanıcı onayı gerektirir
- WeChat arayüzünü asla kontrol etmez ve depoda gerçek kimlik bilgileri saklamaz

Kurulum ve gizlilik notları için [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md) dosyasına bakın.

### `yichen-wecom-local-vault`
macOS'ta yerel WeCom/企业微信 5.x masaüstü veritabanlarını okur, şifresini çözer, sorgular ve dışa aktarır:
- Özel, zaman damgalı düz metin anlık görüntüler oluşturur ve WeCom kapsayıcısına asla geri yazmaz
- Kişiler, oturumlar, mesaj geçmişi, arama ve Markdown/JSON dışa aktarımını destekler
- Mesaj görsellerini, dosyalarını, ses ve videolarını MD5 ile istemcinin yerel önbelleğiyle eşleştirir ve hâlâ yalnızca önizleme olan veya eksik medyaları listeler
- Ham anahtarları, anlık görüntüleri ve sohbet dışa aktarımlarını Git dışında tutar
- Orijinal WeCom uygulamasını kontrol etmez ve mesaj göndermez

### `yichen-grok-consult`
Ana modeli değiştirmeden GPT liderliğindeki bir Codex görevinden Grok'u kullanır:
- Resmî Grok Build CLI üzerinden yerel herkese açık X araması çalıştırır
- Yalıtılmış Grok oturumunun `XSearch` işlemini tamamladığını doğrular
- Gönderi URL'lerini çıkarır ve Snowflake yayımlanma zamanlarını deterministik olarak çözer
- Grok'u mevcut projenin dışında tutar ve yerel dosya, kabuk, MCP, bellek ve alt ajan erişimini kapatır
- Yerel OpenCodex üzerinden isteğe bağlı bağımsız yanıt, inceleme ve sorgulama araçları sunar

Kurulum, gizlilik sınırları ve doğrulama kısıtları için [plugins/yichen-grok-consult/README.md](./plugins/yichen-grok-consult/README.md) dosyasına bakın.

### `yichen-web-research`

Arama, aday inceleme, arşivleme ve isteğe bağlı deşifreyi kapsayan araştırma görevleri için üst düzey yönlendirici:

- Tek aşamalı işleri doğrudan uygun alt Beceriye gönderir
- Bir arama sonucunu asla otomatik indirmeye dönüştürmez
- Sınırlı iş akışları, iddia-kaynak defterleri, çelişki kontrolleri ve kalan boşluk bildirimiyle kanıt kapılı yatay-dikey araştırma kipi ekler
- Güncel yapay zekâ keşfi, genel/dikey web araması, platforma özgü keşif, açık site haritaları ve özgün kaynak doğrulamasını birini diğerinin yerine sessizce koymadan ayrı arka uçlara yönlendirir
- Salt-okunur sosyal platform kullanımını, tam kapsamlı yetkilendirmeyi ve WeChat arayüz kontrolünün olmamasını zorunlu kılar
- Gizli değerleri yazdırmadan, kimlik bilgisi dosya içeriklerini okumadan veya ücretli yoklama isteği yapmadan isteğe bağlı bağdaştırıcı hazırlığını kontrol eden taşınabilir bir salt-okunur arka uç doktoruyla gelir
- Arka uç parametrelerini, sınırları ve oturum durumu kurallarını alt Becerilerde tutar; yönlendirici yalnızca aşama eşlemesini, aşamalar arası yetkilendirme kapılarını, araştırma protokolünü ve doktoru barındırır

Tam aile, isteğe bağlı arka uçlar ve yapılandırma için [yichen-web-research/README.md](./yichen-web-research/README.md) dosyasına bakın.

### `yichen-unified-search`

Herkese açık web ve platforma özgü rotalar genelinde salt-okunur keşif planlaması:

- AI HOT, AnySearch, GitHub, WeChat herkese açık arama, Weibo, Xiaohongshu, Douyin, Toutiao, Zhihu, X, Bilibili, YouTube ve Xiaoyuzhou rotalarını destekler
- Zamana duyarlı yapay zekâ keşfi için yalnızca AI HOT, genel/toplu/dikey web araması için AnySearch ve açık sınırlı site haritası veya mevcut imzalı bir AnySearch adayının açık doğrulaması için yalnızca Firecrawl kullanır
- Sınırlı Zhihu CLI arama/gündem listesi erişimi, anonim öncelikli herkese açık Weibo araması ve Data API veya herkese açık `yt-dlp` yedeğiyle YouTube anahtar kelime/kanal keşfi sunar; medya indirmez
- Sorgu başına tek X Quick çağrısını ve aşamalı arama, deterministik tekilleştirme, kaynak izi koruma, zaman penceresi kontrolleri ve en fazla bir boşluk doldurma turuyla sınırlı çoklu sorgu X Research'ü destekler
- Yerleşik bağdaştırıcılar kaynak izi, kapsam ve sınırlamalarla normalleştirilmiş adaylar üretir; doğrudan GitHub, WeChat Resmî Hesap, Xiaohongshu, Douyin, Toutiao ve Bilibili CLI plan adımları açık bir aşağı akış normalleştirici sağlanmadıkça ham kalır
- Tarayıcı oturumu yeniden kullanımını belgelenmiş sınırlı herkese açık salt-okunur rotalarla sınırlar; özel veri erişimi ve tüm yazma işlemleri bu Becerinin dışındadır
- Eski bağımsız AI HOT Becerisini AI HOT rotası olarak içerir: seçili, günlük ve kategori öğeleri, tam pencere için `--max-pages` sayfalama ve Çince bülten biçimi
- Otomatik yönlendirme her sorguyu ayrı değerlendirir, yerel arama öncesinde "微博上" gibi kanal ifadelerini temizler ve yerel platformlarda AnySearch'e geçmek yerine `--domain`/`--hybrid` seçeneklerini reddeder; WeChat (Sogou) sonuçları geçici yönlendirme bağlantıları taşır, bu nedenle bir makaleyi okumak yine de `mp.weixin.qq.com` bağlantısını gerektirir
- Bu sürümde Reddit için yerel rota yoktur; herkese açık `site:reddit.com` web dizinini kullanın. 2026-10-31 tarihli kontrolde Reddit'in veri merkezi trafiği için JSON uç noktalarını engellediği görülmüştür

Bkz. [ayrıntılı platform matrisi ve rota sınırları](./yichen-unified-search/README.md).

#### Arama sorgusu ve üçüncü taraf veri akışı

Arama metni o rota için seçilen arka uca gönderilir. Arama sorgusuna parola, çerez, kişisel veri, gizli iş bilgisi veya özel URL yazmayın.
Seçilen bir hizmet API veya OAuth kimlik bilgisi gerektirdiğinde bu kimlik bilgisi yalnızca o hizmete protokolüne uygun şekilde gönderilir; bağdaştırıcılar kimlik bilgisi değerlerini aday çıktısına dahil etmez veya bu depoda saklamaz.

| Rota | Yerel süreç dışına gönderilen veri | Alıcı ve sınır |
|---|---|---|
| AI HOT | Yapay zekâ keşif terimleri artı isteğe bağlı kategori/tarih filtreleri | AI HOT herkese açık API'si; üretilen özetler doğrulanmış kanıt değil keşif ipuçlarıdır |
| AnySearch | Genel, toplu veya dikey sorgular ve parametreler; seçilen güncel bir aday URL'si yalnızca doğrulama açıkça istendiğinde | AnySearch; kısa ömürlü aday makbuzu ve imzalama gizli anahtarı yerelde kalır |
| GitHub | Depo arama sorgusu; GitHub API erişimi için yapılandırılmış `gh` kimlik bilgisi kullanılabilir | Yalnızca GitHub; komut `--visibility public` parametresini zorunlu kılar, sorguyu konumsal argüman olarak işler ve özel depoları asla döndürmez |
| Firecrawl | Açıkça sağlanan herkese açık site haritası başlangıç URL'si veya seçilmiş imzalı AnySearch aday URL'si artı protokol `Authorization` başlığındaki Firecrawl API kimlik bilgisi | Yalnızca Firecrawl; tarayıcı çerezleri, sayfa eylemleri veya özel sayfa başlıkları gönderilmez. Bağdaştırıcı kimlik bilgisini yazdırmaz veya saklamaz. Scrape `storeInCache=false` ayarlar; Map önbellek kontrolü iddiasında bulunmaz ve iki rota da sıfır veri saklama garantisi vermez |
| Zhihu | Anahtar kelime sorgusu veya açık gündem listesi isteği; ayrı kurulan çalışma zamanı Keychain durumundan kimlik doğrulaması yapabilir | Ayrı kurulan Open Platform CLI uyumlu çalışma zamanı üzerinden Zhihu; bu depo söz konusu çalışma zamanını, kimlik bilgisini veya özel hesap komutlarını içermez ve bağımsız olarak doğrulamaz |
| Weibo | Herkese açık anahtar kelime sorgusu | Önce geçici bellek içi anonim ziyaretçi oturumuyla `m.weibo.cn`; yalnızca erişim engeli hatası mevcut tarayıcı oturumunu kullanan tek bir sınırlı OpenCLI yedeğine izin verir. Çerez değerleri bağdaştırıcı komutlarına, sonuçlara veya günlüklere girmez |
| YouTube | Anahtar kelime/kanal tanımlayıcısı ve herkese açık arama filtreleri; yapılandırıldığında API anahtarı Data API istek URL'sinde gönderilir | YouTube Data API veya `yt-dlp` aracılığıyla herkese açık YouTube arayüzü; bağdaştırıcı anahtarı yazdırmaz veya saklamaz ve medya indirme yapılmaz |
| X Quick / Research | İstenen sınırlı arama için üretilen her sorgu; Grok CLI hesap OAuth kimlik bilgisini xAI ile kullanır | Resmî Grok CLI ve yerel `x_search` üzerinden xAI; yalnızca açık Grok kota tükenmesi anonim FxTwitter'a izin verir, OpenCLI/xreach ise mevcut görev için açıkça yetkilendirilmedikçe engelli kalır |
| Xiaohongshu / Douyin herkese açık arama | İstenen herkese açık arama terimi | Sınırlı salt-okunur OpenCLI tarayıcı oturumu yeniden kullanımı üzerinden seçili platform; özel koleksiyonlar veya yazma işlemleri için hiçbir yetki devralınmaz |

### `yichen-content-archive`

Bilinen bağlantı ve tam kapsayıcı işleme:

- Onaylanmış web, Xiaohongshu, Douyin, WeChat Resmî Hesap, YouTube, Bilibili ve Xiaoyuzhou hedeflerini okur ve arşivler
- Sürdürülen tek Douyin ve Xiaohongshu bilinen-bağlantı toplayıcılarını barındırır; isteğe bağlı Xiaohongshu'dan Feishu'ya aktarım açık onay gerektirir
- Bilinen WeChat Resmî Hesap makale bağlantılarını kendi `wechat_known_url.py` betiğiyle okur: anonim doğrudan sayfa okuma, görsel gönderi desteği ve gövde görsellerinin yerel kopyaları; eski aktarıcı işletmecisi kapattığı için varsayılan olarak kapalıdır. Hesap geçmişi, metrikler veya yorumlar için yalnızca `yichen-wechat-mp-batch-exporter` kullanın
- Bilinen Xiaoyuzhou bölümlerini resmî ses CDN'inden anonim olarak indirir ve `yichen-asr` (varsayılan olarak StepFun veya yerel Whisper) ile deşifre eder; toplu StepFun çalıştırmaları `--max-transcribe N` gerektirir ve `--download-only` deşifreyi atlar
- Arama/keşfi arşiv katmanının dışında tutar
- Çakışma korumalı çıktılar, sürdürülebilir kontrol noktaları ve açık üzerine yazma korumaları kullanır

### `yichen-bookmarks-export`

Sürdürülen özel yer imi dışa aktarım uygulaması:

- Mevcut görevde her platform ve kapsam için açık yetkilendirme gerektirir
- Xiaohongshu/Douyin Chrome toplayıcılarını ve X yerel dizin dışa aktarıcısını içerir
- Yalnızca bağlantıları dışa aktarır ve bu yetkiyi indirmelere aktarmaz
- Özel URL'leri gömmeden dosyalara referans veren minimal bir teslim çıktısı üretir

Kurulum, bağımlılıklar ve gizlilik sınırları için [yichen-bookmarks-export/README.md](./yichen-bookmarks-export/README.md) dosyasına bakın.

### `yichen-asr`

Tek deşifre giriş noktası (eski `yichen-volc-asr` bununla birleştirilmiştir):

- `transcribe.py` düz metni StepFun veya ücretsiz yerel Whisper (`mlx-whisper` ya da `openai-whisper`) ile işler; motor `--asr-engine`, kayıtlı tercih veya StepFun varsayılanından gelir ve ilk çalıştırma tek seferlik seçim sunar
- Zaman damgası ve SRT işleri varsayılan olarak bir Step Çin-sitesi zaman damgası yürütücüsü kullanır; ücretsiz bir Step reddi (kota veya kimlik doğrulama, hiçbir şey deşifre edilmemişse) yeniden gönderim öncesinde otomatik bir rotayı Doubao 2.0'a geçirebilir
- SRT çıktılı Doubao/Volcengine yürütücüsünü ve bir ffmpeg kaba kurgu zincirini içerir; Step yürütücüleri `YICHEN_STEP_ASR_SCRIPT` ve `YICHEN_STEP_ASR_TIMESTAMPS_SCRIPT` üzerinden kullanıcı tarafından sağlanır
- Yalnızca ortamdan sağlanan App ID, belirteç ve TOS ayarlarını kullanır; Doubao yürütücüsü çalışma kopyasını herkese açık okuma erişimiyle kendi TOS kovanıza yükler, bu nedenle hassas kayıtları o rotadan uzak tutun
- Zaten gönderilmiş bir işi asla sessizce başka bir sağlayıcıya yeniden göndermez

### `yichen-wecom-operations`

Resmî `@wecom/cli` üzerinden sahip onaylı WeCom bulut işlemleri:

- Normal belgeler ve Markdown tabanlı akıllı belgeler oluşturur
- Belgeleri yalnızca izin ve tam hedef kontrollerinden sonra okur veya üzerine yazar
- Yapılacaklar oluşturur ve yönetir; toplantılar ve takvimler yalnızca kurum bu kategorilere izin verdiğinde kullanılabilir
- WeCom masaüstü uygulamasını asla kontrol etmez ve mesaj göndermez
- Kimlik bilgilerini, dahili kimlikleri, makbuzları, kaynak dosyaları ve müşteri verilerini Git dışında tutar
- Yerel görsel yüklemeyi bu depoda dağıtılmayan isteğe bağlı bir harici yardımcı yeteneği olarak ele alır

Kurulum, izin sınırları ve yerel görsel sınırlaması için [yichen-wecom-operations/README.md](./yichen-wecom-operations/README.md) dosyasına bakın.

### `yichen-x-slicer` — Yichen X Slicer

Herkese açık tek bir X durum URL'sini bitmiş sosyal medya varlıklarına dönüştürür:

- Varsayılan olarak doğrulanmış 1080×1440 görsel dizisi, yalnızca PNG içeren bir ZIP ve bir H.264 video üretir
- Varsayılan olarak dahili Sunset Amber şablonunu kullanır ve 11 görsel şablon içerir
- Yalnızca odak Gönderiyi veya doğrulanmış aynı-yazar Dizisini korur; alıntılanan içerikler ve ilgisiz yanıtlar hariç tutulur
- Metin ve fotoğraf duraklamalarını sabit tutar, ek hareketi dört karelik sayfa geçişleriyle sınırlar ve seçilen her yerel videoyu poster karesinde dondurmak yerine medya sahnesi içinde baştan sona oynatır
- Herkese açık verileri FxTwitter üzerinden anonim olarak okur ve X oturum durumunu veya çerezlerini asla kullanmaz
- Asla TTS, seslendirme, arka plan müziği veya müzik üretmez; seçilen yerel video sesi kendi sayfasıyla hizalı kalır, kaynakta sessiz olan aralıklar sessiz kalır ve tamamen sessiz kaynaklı çalıştırmalar ses akışı içermez

Bu Beceriyi doğrudan `npx skills add mcncarl/yichen-skills --skill yichen-x-slicer` komutuyla kurabilirsiniz.

## Proje Yapısı

```text
yichen-skills/
├─ yichen-x-article-draft-uploader/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  └─ scripts/
│     ├─ export_x_cookies_from_chrome.py
│     ├─ parse_markdown.py
│     └─ upload_markdown_to_x_article.py
├─ yichen-wechat-local-vault/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ scripts/
│     ├─ decrypt_all_dbs.py
│     ├─ export_chat.py
│     ├─ extract_keys.py
│     ├─ list_contacts.py
│     ├─ search_sns.py
│     └─ wechat_digest.py
├─ yichen-mac-wechat-dual-open/
│  ├─ SKILL.md
│  ├─ scripts/
│  │  └─ wechat_dual_open.py
│  └─ references/
│     └─ reliability-and-risks.md
├─ yichen-chatgpt-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  └─ agents/
├─ codex-chatgpt/
│  ├─ LICENSE
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ SECURITY.md
│  ├─ config.example.md
│  ├─ agents/
│  ├─ examples/
│  └─ references/
│     └─ setup.md
├─ yichen-agent-memory/
│  ├─ SKILL.md
│  └─ agents/
├─ yichen-wechat-mp-batch-exporter/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-wecom-local-vault/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-web-research/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ scripts/
│  └─ tests/
├─ yichen-unified-search/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ README.zh.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-content-archive/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-bookmarks-export/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  └─ tests/
├─ yichen-asr/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ references/
│  ├─ scripts/
│  │  ├─ transcribe.py
│  │  ├─ asr_engine.py
│  │  ├─ route_asr.py
│  │  ├─ asr_doctor.py
│  │  └─ backends/volc_asr_transcribe.py
│  └─ tests/
├─ yichen-wecom-operations/
│  ├─ SKILL.md
│  ├─ README.md
│  ├─ agents/
│  ├─ references/
│  └─ scripts/
├─ yichen-x-slicer/
│  ├─ SKILL.md
│  ├─ agents/
│  ├─ assets/
│  ├─ references/
│  └─ scripts/
├─ .agents/plugins/
│  └─ marketplace.json
├─ plugins/yichen-grok-consult/
│  ├─ .codex-plugin/plugin.json
│  ├─ .mcp.json
│  ├─ README.md
│  ├─ README.zh.md
│  ├─ mcp/server.mjs
│  ├─ mcp/authenticated-fallback-policy.mjs
│  ├─ mcp/authenticated-fallback-policy.test.mjs
│  └─ skills/yichen-grok-consult/
├─ README.md
├─ README.tr.md
├─ README.zh.md
├─ THIRD_PARTY_NOTICES.md
├─ LICENSE
└─ .gitignore
```

## Gereksinimler

- Claude Code / Codex CLI (yerel beceri yükleme destekli)
- Python Playwright (`yichen-x-article-draft-uploader` için gerekli)
- Python 3.9+
- Bağımlılıklar:
  - X makale taslakları: `pip install playwright pycryptodome && python3 -m playwright install chromium`
  - WeChat yerel kasası: macOS `pycryptodome zstandard` kullanır; Windows yerel CNG ve [sabitlenmiş CPython 3.12 AMD64 bağımlılıklarını](./yichen-wechat-local-vault/references/windows-live.md) kullanır
  - WeChat çift açma: `pip install Pillow`
  - İçerik arşivi (Douyin): `pip install playwright requests && python3 -m playwright install chromium`
  - İçerik arşivi (Xiaohongshu): `pip install requests`
  - ASR (`yichen-asr`): Doubao arka ucu `pip install requests`, yerel `ffmpeg` / `ffprobe` ve kendi TOS kovanızı gerektirir; yerel Whisper `uv tool install mlx-whisper` (veya `openai-whisper`) artı `ffmpeg` gerektirir; Step yürütücüleri ayrı kurulur
  - ChatGPT Web araştırması: ChatGPT'de oturum açmış Chrome ve ajan ortamınızda Chrome/Computer Use yeteneği
  - WeChat MP toplu dışa aktarımı: bilinen URL indirmeleri için Python 3 standart kütüphanesi; hesap geçmişi, metrikler ve yorumlar için yalnızca `wechat-article-exporter` / `wxdown-service`
  - WeCom yerel kasası: `pycryptodome`; `frida` yalnızca açıkça yetkilendirilmiş ham anahtar yakalama için
  - Grok Consult: Node.js 18+, resmî Grok Build CLI ve etkin bir `grok login`; arama dışı danışma araçları için yerel OpenCodex isteğe bağlıdır
  - Sosyal yer imi dışa aktarıcısı: Xiaohongshu/Douyin `chrome:control-chrome` destekli bir ajan ortamı gerektirir; X rotası isteğe bağlı olarak sürümünde `graphql-only` içeren bir Field Theory `ft` CLI derlemesi gerektirir
  - Web Araştırma ailesi: beş aile dizininin tamamını birlikte kurun. Unified Search bağdaştırıcıları Python standart kütüphanesi ve isteğe bağlı `idna` kullanır; diğer aile üyeleri yukarıda listelenen bağımlılıklarını korur. İsteğe bağlı rotalar AnySearch, Firecrawl, Zhihu Open Platform CLI uyumlu çalışma zamanı, OpenCLI, resmî Grok CLI, `xreach`, `gh`, `yt-dlp`, `bili` veya `ffmpeg` gibi ayrı kurulan servis/çalışma zamanlarını gerektirir
  - Birleşik YouTube araması ayrı yapılandırılmış bir YouTube Data API kimlik bilgisi kullanabilir veya herkese açık `yt-dlp` listelemesine geri dönebilir; asla medya indirmez
  - Birleşik Weibo araması anonim başlar; belgelenmiş erişim engeli yedeği OpenCLI ve mevcut oturum açılmış bir Chrome oturumu gerektirir
  - Yichen X Slicer: Node.js 18+, Playwright, yerel Chrome, `ffmpeg` ve `ffprobe`

## Kurulum

Bu depoyu yerel beceriler dizininize kopyalayın:

- Yaygın Claude yolu: `~/.claude/skills/`
- Yaygın Agents yolu: `~/.agents/skills/`
- Kurulumunuz destekliyorsa özel bir beceri yolu da çalışır

Dizin adlarını değiştirmeden koruyun:
- `yichen-x-article-draft-uploader`
- `yichen-wechat-local-vault`
- `yichen-mac-wechat-dual-open`
- `yichen-chatgpt-web-research`
- `codex-chatgpt`
- `yichen-agent-memory`
- `yichen-wechat-mp-batch-exporter`
- `yichen-wecom-local-vault`
- `yichen-web-research`
- `yichen-unified-search`
- `yichen-content-archive`
- `yichen-bookmarks-export`
- `yichen-asr`
- `yichen-wecom-operations`
- `yichen-x-slicer`

`yichen-grok-consult`, tek başına kopyalanan bir beceri değil bir Codex eklentisidir. Bu deponun pazar yeri üzerinden kurun:

```bash
codex plugin marketplace add mcncarl/yichen-skills --ref main
codex plugin add yichen-grok-consult@yichen-skills
```

## Hızlı Başlangıç (3 Dakika)

### B) `yichen-x-article-draft-uploader` etkinleştirme

1. Beceri README dosyasındaki güvenli komutu izleyerek sabitlenmiş `x-article-draft-uploader-v1.0.1` etiketini kurun
2. Becerinin `requirements.txt` dosyasındaki tam Python bağımlılıklarını kurun, ardından `python3 -m playwright install chromium` çalıştırın
3. Chrome'un X'te oturum açmış olduğundan emin olun; Ailu kullanıcıları Ayarlar'dan çerezleri Chrome'dan içe aktarabilir, JSON yapıştırabilir veya JSON dosyası seçebilir
4. "upload this Markdown article to X Articles draft" deyin veya betiği doğrudan çalıştırın
5. Beceri yeni bir taslak oluşturur ve doğrular; yayımlamaz
6. Sabitlenmiş kurulum komutu ve kontroller için [yichen-x-article-draft-uploader/README.md](./yichen-x-article-draft-uploader/README.md) dosyasına bakın

### C) `yichen-mac-wechat-dual-open` etkinleştirme

1. Python bağımlılığını kurun: `pip3 install Pillow`
2. Claude Code'da "帮我微信双开" veya "WeChat dual open" deyin
3. Beceri `~/Applications/WeChat-2.app` konumunda mavi simgeli ikinci bir WeChat oluşturur
4. Tüm komutlar için `yichen-mac-wechat-dual-open/SKILL.md` dosyasına bakın

### D) `yichen-wechat-local-vault` etkinleştirme

1. Önce kaynağı seçin: macOS yerel kasası, Windows yerel yakalama veya açıkça ayrılmış bir Windows düz metin anlık görüntüsü.
2. macOS'ta `pycryptodome zstandard` kurun, ardından sohbet ayrıştırma, dışa aktarım, Moments veya Favoriler isteyin. Beceri mevcut Mac kurulumuna ve iş akışı seçimine rehberlik eder.
3. Windows'ta CPython 3.12 AMD64 ve [Windows yakalama kılavuzundaki](./yichen-wechat-local-vault/references/windows-live.md) sabitlenmiş bağımlılığı kullanın. Elle giriş yapın, `windows discover` ile yetkili kaynağı seçin ve tam yerel yakalama için `windows capture --scope all --source-id SOURCE_ID` kullanın; varsayılan `capture` kapsamı yalnızca sohbet veritabanlarını seçer.
4. Windows sorgu/arama/dışa aktarım için `snapshot` rotasını kullanın. Bu rota veriyi yenilemez; güncel mesajlar gerektiğinde yeniden yakalama yapın.
5. Platforma özel komutlar, gizlilik yolları ve test edilmiş izin/sürüm sınırları için [Beceri README](./yichen-wechat-local-vault/README.md) dosyasına bakın.

### E) İçerik üreticisi video iş akışını etkinleştirme

1. Playwright, requests ve ffmpeg kurun
2. Bilinen Douyin veya Xiaohongshu referans medyalarını yerelde kaydetmek için `yichen-content-archive` kullanın
3. Kaydedilmiş konuşan kafa videolarını deşifre etmek, altyazı eklemek veya kaba kurgu yapmak için `yichen-asr` kullanın

### F) `yichen-chatgpt-web-research` etkinleştirme

1. Chrome'un hedef ChatGPT hesabında oturum açmış olduğundan emin olun
2. Bir Pro rotası doğrulanması gerektiğinde ChatGPT sekmesini veya profilini görünür tutun
3. Resmî site araştırması isteyin; örneğin: "Use ChatGPT Web to research Anthropic and save a Markdown report"
4. Beceri tam yanıtı bekler, işaretçiyi doğrular ve ham/okunabilir Markdown raporlarını kaydeder

### F2) `codex-chatgpt` etkinleştirme

1. `npx skills add mcncarl/yichen-skills --skill codex-chatgpt` ile kurun
2. Saf araştırma için resmî ChatGPT web sitesinin Chat kipini ve görünür bir `Pro` rotasını sunduğunu doğrulayın
3. Kod, hibrit veya inceleme için [codex-chatgpt/references/setup.md](./yichen-codex-chatgpt/references/setup.md) belgesinde açıklanan özel Uygulama ve uyumlu salt-okunur çalışma zamanını yapılandırın
4. Doldurulmuş yerel yapılandırmayı ve tüm kanıtları kaynak depolarının dışında tutun

### G) `yichen-agent-memory` etkinleştirme

1. `yichen-agent-memory/SKILL.md` dosyasının yüklü beceri yolunuzda bulunduğundan emin olun
2. Codex'ten "install Agent Memory Vault" veya "set up a local Agent Memory Vault vault" isteyin
3. Beceri özel bir yerel kasa oluşturmak için [mcncarl/agent-memory-vault](https://github.com/mcncarl/agent-memory-vault) deposunu kullanır
4. Kurulumdan sonra arama, görev sonu temizliği ve dönemsel inceleme için `codex_memory_search.py`, `codex_memory_closeout.py` ve `codex_memory_audit.py` betiklerini kullanın

### H) `yichen-wechat-mp-batch-exporter` etkinleştirme

1. `yichen-wechat-mp-batch-exporter/SKILL.md` dosyasının yüklü beceri yolunuzda bulunduğundan emin olun
2. Bilinen makale URL'leri için doğrudan Markdown indirmesi isteyin
3. Hesap geçmişi için `WECHAT_ARTICLE_EXPORTER_DIR` değişkenini yapılandırın veya `wechat-article-exporter` tarafından desteklenen herkese açık dışa aktarım rotasını kullanın
4. Okuma sayıları ve yorumlar için `WXDOWN_SERVICE_DIR` değişkenini yapılandırın ve herhangi bir yerel yardımcıyı başlatmadan önce kimlik bilgisi yakalama iş akışını onaylayın
5. Metrik, yorum, vekil sunucu, sertifika veya WeChat masaüstü iş akışlarını kullanmadan önce [yichen-wechat-mp-batch-exporter/README.md](./yichen-wechat-mp-batch-exporter/README.md) dosyasına bakın

### I) `yichen-wecom-local-vault` etkinleştirme

1. `yichen-wecom-local-vault/SKILL.md` dosyasının yüklü beceri yolunuzda bulunduğundan emin olun
2. `pycryptodome` kurun; `frida`'yı yalnızca açıkça yetkilendirilmiş yerel ham anahtar yakalamaya ihtiyacınız varsa kurun
3. Yerel WeCom verilerinizi incelemeyi veya dışa aktarmayı isteyin; iş akışı orijinal uygulamayı asla kontrol etmez

### J) `yichen-grok-consult` etkinleştirme

1. Resmî Grok Build CLI'ı kurun ve `grok login` çalıştırın
2. `mcncarl/yichen-skills` pazar yerini ekleyin ve `yichen-grok-consult` eklentisini kurun
3. Yeni bir Codex görevi başlatın
4. GPT'den Grok ile herkese açık X gönderilerini aramasını veya Grok'tan ikinci bir görüş almasını isteyin
5. Vekil sunucular veya OpenCodex yapılandırmadan önce [plugins/yichen-grok-consult/README.md](./plugins/yichen-grok-consult/README.md) dosyasına bakın

### K) `yichen-bookmarks-export` etkinleştirme

1. `yichen-bookmarks-export/SKILL.md` dosyasının yüklü beceri yolunuzda bulunduğundan emin olun
2. Xiaohongshu veya Douyin için mevcut Chrome oturumuyla giriş yapın ve hedef favoriler sayfasını açın
3. X için ayrı kurulan `ft --version` çıktısının `graphql-only` içerdiğini doğrulayın
4. Mevcut görev için platformları, dışa aktarım kapsamını ve çıktı dizinini açıkça yetkilendirin
5. Beceri yalnızca bağlantıları dışa aktarır ve doğrular; medyayı otomatik indirmez veya koleksiyon durumunu değiştirmez

### L) Web Araştırma ailesini etkinleştirme

1. `yichen-web-research`, `yichen-unified-search`, `yichen-content-archive`, `yichen-bookmarks-export` ve `yichen-asr` becerilerini birlikte kurun
2. Bu beş Beceriyi Skills CLI ile bu depodan kurmak için şunu çalıştırın:

```bash
npx skills add mcncarl/yichen-skills --skill yichen-web-research
npx skills add mcncarl/yichen-skills --skill yichen-unified-search
npx skills add mcncarl/yichen-skills --skill yichen-content-archive
npx skills add mcncarl/yichen-skills --skill yichen-bookmarks-export
npx skills add mcncarl/yichen-skills --skill yichen-asr
```

3. Yalnızca hedeflediğiniz rotalar için gereken isteğe bağlı üçüncü taraf arka uçları kurun ve kimlik doğrulaması yapın; çalıştırılabilir dosyaları ve kimlik bilgileri burada paketlenmemiştir
4. `python3 yichen-web-research/scripts/validate_family.py` çalıştırın
5. Çok aşamalı işler için `$yichen-web-research` ile başlayın veya yalnızca arama, bilinen bağlantı arşivi, yer imi dışa aktarımı ya da yerel ASR için doğrudan ilgili alt beceriyi çağırın
6. Ücretli veya hesap oturumlu bir rotayı etkinleştirmeden önce yukarıdaki sorgu/veri akışı tablosunu ve [yichen-web-research/README.md](./yichen-web-research/README.md) dosyasını inceleyin

## Bu Projeyi Destekleyin

Bu Beceriler işinize yarıyorsa aşağıdaki WeChat takdir kodu üzerinden gönüllü olarak bana bir kahve ısmarlayabilirsiniz.

<p align="center">
  <img src="./assets/wechat-reward-code.jpg" width="280" alt="Yichen'in WeChat takdir kodu">
</p>

Destek tamamen gönüllüdür. Ücretli hizmet, teknik destek, özellik teslimatı veya yanıt süresi taahhüdü oluşturmaz.

## X Çerez Yönetimi

Bu depo gerçek kimlik bilgileri veya çerez şablonları içermez.

`yichen-x-article-draft-uploader`, mevcut X çerezlerini kullanıcının yerel Chrome profilinden özel bir Playwright çerez dosyasına dışa aktarabilir. Ailu kullanıcıları dosyayı doğrudan yönetmek yerine normalde Ailu Ayarlarındaki üç içe aktarma seçeneğini kullanmalıdır:

```bash
python3 ~/.agents/skills/x-article-draft-uploader/scripts/export_x_cookies_from_chrome.py \
  --output ~/.ailu/secrets/x/cookies.json
```

Kanonik dizin `0700` ve dosya `0600` izinlerine sahiptir. Dosya hassastır: asla commit etmeyin, bir issue'ya yüklemeyin veya tanılama raporuna eklemeyin. `.gitignore` çerez JSON dosyalarını zaten yok sayar.

## Güvenlik Notları

- Gerçek belirteç/çerez değerleri dahil edilmez
- Geçmiş/önbellek çıktıları izleme dışında bırakılır
- Kişisel mutlak yollar genel biçimlerle değiştirilir
- Üçüncü taraf AppID, AppToken, TableID, kova adları ve ASR belirteçleri ortam değişkenleri veya özel yapılandırma üzerinden sağlanmalıdır
- WeChat dışa aktarıcı kimlik doğrulama anahtarları, kimlik bilgisi dosyaları, QR gizli anahtarları, yakalanan çerezler ve indirilen makale arşivleri yerelde ve gizli kalmalıdır
- `yichen-grok-consult` sabit vekil sunucu veya kimlik bilgisi içermez; Grok sorguları ve sonuçları yine de xAI'ye gönderilir ve yalıtılmış yerel oturum dizininde tutulur
- Web Araştırma ailesi kişisel mutlak yol, App ID, belirteç, sabit Keychain öğesi veya özel vekil sunucu değeri içermez; hesap destekli rotalar isteğe bağlı kalır
- `codex-chatgpt` yalnızca orkestrasyon protokolünü içerir; özel MCP çalışma zamanı, Runtime Key, Tunnel/App tanımlayıcıları, tarayıcı oturumu, ekran görüntüleri ve doldurulmuş yerel yapılandırma dağıtılmaz
- Unified Search her sorguyu yalnızca veri akışı tablosunda açıklandığı şekilde o rota için seçilen üçüncü taraf arka uca gönderir. Yerel imzalama materyali, tarayıcı çerez değerleri ve üçüncü taraf kimlik bilgileri depo dosyalarına veya normalleştirilmiş aday çıktısına dahil edilmez
- Anonim Weibo ziyaretçi oturumu yalnızca bağdaştırıcı belleğinde yaşar. Belgelenmiş OpenCLI yedeği kullanıldığında tarayıcı oturumunu OpenCLI yönetir ve bağdaştırıcı Çerez değerlerini kabul etmez veya yazdırmaz
- Firecrawl Scrape `storeInCache=false` ayarlar; Map önbellek kontrolü iddiasında bulunmaz ve iki ayar da sıfır veri saklama garantisi olarak yorumlanamaz veya tanıtılamaz
- `yichen-wecom-operations` hiçbir Bot ID, Secret, dahili kullanıcı/kaynak kimliği, makbuz, kaynak belge veya müşteri verisi içermez; yetkilendirme kiracıya özel kalır

Herkese açık bir depoda gerçek çerezleri yanlışlıkla ifşa ettiyseniz bunları hemen yenileyin.

## Sıkça Sorulan Sorular

### Bir beceri neden tetiklenmiyor?
- Beceri klasörünün gerçekten yüklenen beceri yolunuzda olduğunu doğrulayın
- Oturumu yeniden başlatıp tekrar deneyin
- `SKILL.md` üst verisindeki `name` ve `description` alanlarını kontrol edin

### X Articles taslak yüklemesi neden başarısız oldu?
- Chrome'un hâlâ X'te oturum açmış olup olmadığını kontrol edin
- Geçici çerezleri yeniden dışa aktarın
- Python Playwright'ın kurulu olduğunu doğrulayın
- Yerel Markdown/görsel yollarının var olduğunu doğrulayın

### Kendi Obsidian yolumu kullanabilir miyim?
- Evet. Beceri dosyalarındaki örnek yolları değiştirin
- `<OBSIDIAN_VAULT>/...` yalnızca bir örnektir

## Yeniden Dağıtanlar İçin

Bu depo yalnızca kişisel öğrenme ve ticari olmayan kişisel kullanım için yayımlanmıştır. Önceden açık yazılı izin olmadan ticari hizmetler, müşteri teslimatı, ücretli ürünler, şirket içi araç setleri, pazar yeri paketleri, kurslar veya gelir getirici başka hiçbir amaç için kullanmayın. Ticari yetkilendirme talep etmek için WeChat üzerinden `yichen365ai` hesabıyla iletişime geçin ve doğrulama mesajına `Commercial Authorization` yazın.

Kişisel çalışma için forklarsanız en azından şu dosyaları koruyun:
- `README.md`
- `README.zh.md`
- `LICENSE`
- `.gitignore`
- `THIRD_PARTY_NOTICES.md`
- `yichen-x-article-draft-uploader/README.md`

Bu depoyu herkese açık bir beceri paketi olarak yeniden yayımlamayın veya yeniden paketlemeyin. Kullanıcılara gerçek kimlik bilgilerini veya özel verileri yayımlamamalarını her zaman hatırlatın.

## Teşekkürler

X Articles taslak iş akışı ve Markdown ayrıştırma yaklaşımının bazı bölümleri şu kaynağa atıfla uyarlanmıştır:

- `wshuyi/x-article-publisher-skill`
  - Depo: <https://github.com/wshuyi/x-article-publisher-skill>
  - Belgeler: <https://github.com/wshuyi/x-article-publisher-skill/blob/main/README_CN.md>
  - Lisans: MIT

`yichen-wechat-local-vault` içindeki WeChat veritabanı şifre çözme yaklaşımı şu kaynaktan uyarlanmıştır:

- `zhuyansen/wx-favorites-report`
  - Depo: <https://github.com/zhuyansen/wx-favorites-report>
  - Yazar: zhuyansen
  - Lisans: MIT
  - Özellikle: `CCKeyDerivationPBKDF` anahtar çıkarımı için frida kanca yöntemi ve SQLCipher 4 sayfa düzeyinde şifre çözme mantığı

`yichen-mac-wechat-dual-open` içindeki WeChat çift açma yöntemi şunlara dayanır:

- [@koffuxu](https://x.com/koffuxu) — orijinal rehber (2026-04): [Mac 微信双开最完美方案](https://x.com/koffuxu/status/2043110831584690427)
- [@MinLiBuilds](https://x.com/MinLiBuilds) — bağımsız doğrulama (2026-04)

`yichen-grok-consult` içindeki yalıtılmış Grok Build arama tasarımı şu kaynaktan esinlenmiştir:

- [`sudoHG/codex-grok-search`](https://github.com/sudoHG/codex-grok-search) — MIT lisanslı herkese açık referans; buraya kaynak kod dahil edilmemiştir

`yichen-bookmarks-export` içindeki X yer imi rotası şunu çağırır:

- [`afar1/fieldtheory-cli`](https://github.com/afar1/fieldtheory-cli) — MIT lisanslı isteğe bağlı harici çalışma zamanı; burada Field Theory kaynağı veya ikili dosyası dağıtılmaz
- Gerekli `graphql-only` işaretçisi resmî bir yukarı akış sürüm adını değil kullanıcı tarafından sürdürülen değiştirilmiş bir derlemeyi ifade eder; bu derleme bu depo tarafından dağıtılmaz

`yichen-wecom-operations` ayrı kurulan resmî WeCom CLI'ını çağırır:

- [`WeComTeam/wecom-cli`](https://github.com/WeComTeam/wecom-cli) — MIT lisanslı harici çalışma zamanı; burada yukarı akış kaynağı, ikili dosya, Bot kimlik bilgisi veya kiracı verisi dağıtılmaz
- Yerel görsel yükleme `doc +doc_upload_image` sunan isteğe bağlı kullanıcı kaynaklı bir yardımcı gerektirir; bu yerel uzantı burada dağıtılmaz veya yukarı akış özelliği olarak sunulmaz

`yichen-unified-search` içindeki YouTube arama/filtreleme uygulaması kısmen şu kaynaktan türetilmiştir:

- [`joeseesun/yt-search-download`](https://github.com/joeseesun/yt-search-download) (Joe Sun) — MIT lisanslı; yukarı akış telif hakkı ve tam lisans metni `licenses/joeseesun-yt-search-download-LICENSE.txt` içinde korunmuştur
- Yalnızca herkese açık arama/filtreleme davranışı uyarlanmıştır. Bu deponun bağdaştırıcısı normalleştirilmiş keşif adayları üretir ve yukarı akış indirme, altyazı veya medya çıkarma iş akışını içermez

Zhihu rotası, üretici kökeni bu depo tarafından bağımsız olarak doğrulanmayan, ayrı kurulan Zhihu Open Platform CLI uyumlu bir çalışma zamanını çağırır:

- Bu depoda hiçbir Zhihu CLI kaynağı veya ikili dosyası dağıtılmaz ve bu depo söz konusu harici çalıştırılabilir dosya üzerinde hak vermez
- Kullanıcılar kurmadan veya kullanmadan önce çalışma zamanının dağıtıcısını belirlemeli ve sürüme özgü lisans ile hizmet koşullarını incelemelidir

Ayrıntılar için `THIRD_PARTY_NOTICES.md` dosyasına bakın.

## Uyumluluk Sınırı

- Bu proje AI HOT, AnySearch, Firecrawl, Zhihu, Weibo, YouTube, Google, X, xAI, OpenAI, WeChat, Tencent, Xiaohongshu, Douyin veya Field Theory ile bağlantılı, onlar tarafından onaylanmış veya desteklenmiş değildir.
- Bu depo yalnızca kişisel öğrenme ve ticari olmayan kişisel iş akışı kullanımı içindir.
- Önceden yazılı izin olmadan ticari kullanım, müşteri teslimatı, yeniden satış, ücretli yeniden dağıtım, pazar yeri paketlemesi, kurs paketlemesi ve şirket içi kurulum yasaktır.
- Kullanıcılar X platformu koşullarına/politikalarına ve yerel yasalara uymaktan sorumludur.
- Koleksiyon dışa aktarma iş akışları yalnızca kullanıcının erişim yetkisine sahip olduğu veriler içindir; erişim kontrollerini, CAPTCHA'yı, hız sınırlarını veya platform güvenlik önlemlerini aşmayın.
- Arama sorguları ve seçilen herkese açık URL'ler yukarıda açıklanan yönlendirilen üçüncü taraf hizmetlere iletilir. Kullanıcılar bu hizmetlerin güncel koşullarından, gizlilik politikalarından, kotalarından ve veri saklama uygulamalarından sorumludur; bir arama kutusunu asla gizli anahtarlar veya özel veriler için kanal olarak kullanmayın.
- Arama kartları, üretilen özetler, metrikler ve açılan sayfalar, ilgili iddia uygun bir özgün kaynakla doğrulanana kadar aday kanıt olarak kalır.
- X dahili GraphQL ve platform-DOM rotaları resmî olmayan uyumluluk yöntemleridir; değişebilir veya platform kontrollerini tetikleyebilir.
- `yichen-wechat-local-vault` yalnızca kişisel kullanım içindir — yalnızca kendi sohbet verilerinizin şifresini çözün ve okuyun.
- `yichen-wecom-local-vault` yalnızca sahip onaylı yerel veriler içindir — anahtarları, düz metin anlık görüntüleri veya sohbet dışa aktarımlarını asla yüklemeyin.
- `yichen-wecom-operations` yalnızca sahip onaylı bot kaynakları içindir — asla mesaj göndermeyin, istemciyi otomatikleştirmeyin, eksik kurumsal yetkilendirmeyi aşmayın veya kimlikleri, makbuzları, kaynak belgeleri ve müşteri verilerini commit etmeyin.
- Gerçek hesap kimlik bilgilerini (örneğin `cookies.json`, `wechat-keys.json`) asla herkese açık depolara yüklemeyin.
- Gerçek sohbet kayıtlarını, WeChat veritabanlarını, müşteri verilerini, özel notları, API anahtarlarını, yerel yolları veya diğer kişisel verileri asla yüklemeyin.

## Lisans

Kişisel Öğrenme ve Ticari Olmayan Kullanım Lisansı. Bkz. [LICENSE](./LICENSE).

## Beceri sürüm bakımı

Salt-okunur sapma kontrolleri, kapsamlı güncellemeler ve ayrı herkese açık/özel çalışma zamanı sürüm sınırları için [源码与安装版维护](docs/skill-maintenance.md) belgesine bakın.
