# PDF Metadata Düzenleyici

PDF dosyalarının Info sözlüğünü ve XMP metadata'sını görüntüleyip düzenleyen Windows masaüstü uygulaması (Python + PySide6 + pikepdf).

## Kurulum (kursiyerler için)
- Göndermeniz gereken tek dosya: `dist\PDFMetadataDuzenleyici_Kurulum_<sürüm>.exe`.
- Python, tüm kütüphaneler ve yazı tipleri kurulumun içindedir; hedef bilgisayarda internet veya Python gerekmez. Windows 10/11 64 bit gerekir.
- Yönetici izni istemez (kullanıcıya kurulur); sihirbazda istenirse tüm kullanıcılar için kurulabilir. Masaüstü ve Başlat menüsü kısayolu oluşturur, istenirse PDF'lerin "Birlikte aç" listesine eklenir.
- Kurulu sürümde çıktılar `Belgeler\PDF Metadata Düzenleyici\çıktı belgeleri` klasörüne kaydedilir.
- Kaldırma: Ayarlar → Uygulamalar (veya Başlat menüsündeki kaldırma kısayolu). Şablonlar ve dijital imzalar `%APPDATA%\PDFMetadataDuzenleyici` klasöründe kalır.
- Kurulum dosyası imzasız olduğu için Windows SmartScreen "Windows bilgisayarınızı korudu" uyarısı gösterebilir: **Ek bilgi → Yine de çalıştır**.
- Yeni kurulum dosyası üretmek: `kurulum_olustur.bat` (Inno Setup 6 gerekir). Sürüm numarası `installer\kurulum.iss` içindeki `AppVersion` satırındadır.

## Çalıştırma
- **Kurulumsuz:** `dist\PDFMetadataDuzenleyici.exe` (Python gerekmez). Bir PDF'i exe'nin üzerine sürükleyerek de açabilirsiniz.
- **Kaynaktan:** `calistir.bat` (eksik kütüphaneleri kendisi kurar).
- **Exe'yi yeniden derlemek:** `exe_olustur.bat`

## Özellikler
**Tek Dosya Düzenle**
- PDF açma: dosya seçme diyaloğu veya pencereye sürükle-bırak. Şifreli PDF'lerde şifre sorulur ve kaydederken şifreleme korunur.
- Dosya Bilgileri paneli (salt okunur): boyut, PDF sürümü, sayfa sayısı ve boyutu, şifreleme, linearized, form, ekler, nesne sayısı, belge ID, revizyon sayısı.
- Standart alanlar: Başlık, Yazar, Konu, Anahtar Kelimeler, Oluşturan, Üretici, Trapped.
- Tarihler: takvim, saat dilimi ve ham PDF tarih metni (`D:YYYYMMDDHHmmSS+HH'mm'`) birbirine bağlı olarak düzenlenir.
- Diğer / özel alanlar: PDF'teki standart dışı tüm Info anahtarları listelenir; yenileri eklenip silinebilir.
- XMP: özellik tablosu (metin / Seq liste / Bag küme) ve ham XML editörü (iki görünüm otomatik eşitlenir), Info → XMP eşitleme, XMP'yi tamamen kaldırma.
- Tüm metadatayı temizleme.
- **Geri Al / Yinele** (Ctrl+Z / Ctrl+Y veya üst çubuktaki düğmeler): alan, tablo, XMP, şablon uygulama ve temizleme işlemlerinin tümü adım adım geri alınabilir. Metin kutusunda imleç varken Ctrl+Z o kutunun kendi geri almasını yapar.
- **Dosyadaki Haline Döndür**: tüm alanları dosyadan okunan değerlere döndürür (bu da geri alınabilir).
- **Değişiklikleri Göster** (Ctrl+D): dosyadaki ve ekrandaki Info/XMP değerlerini yan yana, renkli olarak karşılaştırır.
- **Kaydet** (Ctrl+S): önce öncesi/sonrası karşılaştırma ekranı açılır; **Onayla ve Kaydet** denince yeni dosya soru sorulmadan **çıktı klasörüne** `<ad>_duzenlenmis.pdf` olarak kaydedilir (aynı ad varsa `(2)`, `(3)` … eklenir). Konum seçmek için Dosya → Farklı Kaydet… (Ctrl+Shift+S).
- Kaydetme her zaman **yeni dosya** olarak yapılır; kaynak dosyanın üzerine yazılmaz.

**Çıktı klasörü**
- Varsayılan: programın yanındaki `çıktı belgeleri` klasörü (yoksa oluşturulur). Exe için bu, exe'nin bulunduğu klasördür.
- Tek dosya sekmesinin altındaki **Değiştir…** / **Aç** düğmeleriyle veya Dosya menüsünden değiştirilir; seçim kalıcıdır ve toplu düzenleme de aynı klasörü kullanır.

**Şablonlar** (iki sekmede de)
- Sık kullanılan alan değerlerini ad vererek kaydedip tek tıkla uygulama.
- Tek dosyada: şablondaki alanlar ekrana yazılır, diğer alanlara dokunulmaz.
- Toplu düzenlemede: şablondaki alanlar işaretlenir, diğerlerinin işareti kaldırılır (işaretli + boş = alan silinir).
- Şablonlar `%APPDATA%\PDFMetadataDuzenleyici\sablonlar.json` dosyasında saklanır (Yardım → Hakkında'da yolu görünür).

**Toplu Düzenleme**
- Birden fazla PDF ekleme (sürükle-bırak destekli).
- Yalnızca işaretlenen alanlar değişir; işaretli ve boş bırakılan alan silinir.
- Özel alan ekleme ve güncelleme, önce tümünü temizleme, Info → XMP yansıtma.
- Çıktı klasörü ve dosya adı eki (varsayılan `_duzenlenmis`) seçilebilir.
- **Önizle**: dosyaları kaydetmeden her dosyada hangi alanın nasıl değişeceğini gösterir; pencereden doğrudan uygulanabilir.
- Şifreli dosyaların şifresi bir kez sorulur, önizleme ve uygulama arasında hatırlanır.

**Online Düzenleme** (3. sekme) — 10-15 dosyayla hızlı çalışmak için
- PDF'leri sürükleyip bırakın veya **+ PDF Ekle** ile seçin; aynı dosya iki kez eklenmez.
- Listeden bir dosyaya tıklayınca sağda **Tek Dosya Düzenle** ile aynı panel açılır. Her dosyanın kendi değerleri ve geri al geçmişi vardır; dosyalar arasında gezinirken düzenlemeler kaybolmaz (Ctrl+PgUp / Ctrl+PgDown ile önceki/sonraki dosya).
- Listede durum işaretleri: ○ değişiklik yok · ● değişti, kaydedilmedi · ✔ kaydedildi · 🔒 imzalı (değiştirilemez).
- Her dosya kendi **Kaydet** düğmesiyle (karşılaştırma ekranı ile) veya **Tümünü Kaydet** ile tek tıkla çıktı klasörüne kaydedilir. Tümünü Kaydet'te istenirse yalnızca değiştirilen dosyalar kaydedilir; imzalama açıksa hepsi imzalanır.
- **👁 Görüntüle** (veya çift tıklama / Boşluk tuşu): PDF'in içeriği uygulama içinde açılan hızlı önizleme penceresinde gösterilir; yakınlaştırma, sayfaya/genişliğe sığdırma ve ← → tuşlarıyla önceki/sonraki dosya.
- Kaydedilmemiş değişiklik varken dosyayı listeden çıkarırken veya programı kapatırken uyarı verilir.

**PDF Küçült** (4. sekme)
- PDF'i sürükleyip bırakın veya seçin, hedef boyutu MB olarak yazın, **Küçült ve Kaydet**'e basın.
- Önce kalite kaybı olmadan sıkıştırılır; yetmezse resimler adım adım daha düşük kalite/çözünürlükle yeniden kaydedilir ve hedefe sığan **en kaliteli** hali seçilir. Yazılar ve vektör çizimler bozulmaz; metadata aynen korunur.
- Hedefe ulaşılamazsa (ör. yalnızca yazıdan oluşan PDF) elde edilebilen en küçük hali kaydedilir ve uyarı gösterilir.
- Sonuç çıktı klasörüne `<ad>_kucultulmus.pdf` olarak kaydedilir; önce/sonra boyutu gösterilir, küçültülmüş hali uygulama içinde görüntülenebilir.
- Dijital imzalı belgeler küçültülemez (imza bozulur).

**Belge Okuyucu** (5. sekme)
- PDF'leri ekleyin (sürükle-bırak destekli); seçili belgenin tüm verileri bölümler halinde görünür: dosya bilgileri, Info, XMP, güvenlik/izinler ve imza, belge yapısı (dil, etiketleme, çıktı amacı…), sayfalar, fontlar, resimler, ekli dosyalar, form alanları. Ham XMP ve tüm rapor ayrı sekmelerde düz metin olarak da gösterilir.
- Kopyalama: **Tümünü Kopyala**, **Seçiliyi Kopyala** (Ctrl+C), **Ham XMP'yi Kopyala**; satıra çift tıklama değeri kopyalar, sağ tık menüsünde değer/satır/bölüm kopyalama vardır.
- **Bilgileri Şablon Olarak Kaydet**: belgedeki metadata (standart alanlar, istenirse tarihler, özel alanlar ve XMP'nin tamamı) tek tıkla şablon olur. Diğer sekmelerde Şablon listesinden seçip **Uygula** ile yeni belgelere aktarılır; böylece daha önce kesilmiş bir faturanın bilgileri elle girilmeden yeni belgelere kopyalanabilir.
- Şablon XMP içeriyorsa: Tek Dosya / Online Düzenleme'de XMP de ekrana yüklenir; Toplu Düzenleme'de "Şablondaki XMP'yi de yaz" seçeneği işaretlenir. ("XMP'yi yalnızca Info alanlarından oluştur" seçeneği açıksa XMP kayıtta Info'dan yeniden oluşturulur.)
- **Tek Dosya Düzenle'de Aç** ve **Görüntüle** düğmeleriyle belge doğrudan düzenlenebilir veya önizlenebilir.

**Dijital İmza** (6. sekme)
- Her şirket için bir kez dijital imza oluşturulur (şirket, imzalayan, unvan, e-posta, konum, imza nedeni, geçerlilik süresi). Hazır bir .pfx/.p12 sertifikası da içe aktarılabilir.
- Tek dosya ve toplu düzenleme sekmelerinin altındaki **🔒 İmzala** kutusu işaretlenip imza seçilince kaydedilen **her belge** otomatik imzalanır; seçim hatırlanır.
- İmza, PAdES sertifikasyon imzasıdır (DocMDP: değişikliğe izin yok). İmzalı belge bu programda düzenlenemez; başka bir programla değiştirilirse PDF okuyucuları imzayı geçersiz gösterir.
- İsteğe bağlı olarak son sayfanın sağ alt köşesine görünür imza kutusu eklenir.
- Üretilen sertifikalar kendinden imzalıdır: alıcı, **Sertifikayı Dışa Aktar (.cer)** ile verilen dosyayı Adobe Reader'da güvenilir kimliklere eklemezse "kimlik doğrulanamadı" uyarısı görebilir.
- İmzalar `%APPDATA%\PDFMetadataDuzenleyici\imzalar` klasöründe saklanır; anahtar şifreleri Windows DPAPI ile korunur (yalnızca aynı Windows kullanıcısı kullanabilir).

## Yapı
- `pdfmeta/core.py`: okuma ve yazma motoru (arayüzden bağımsız).
- `pdfmeta/widgets.py`: tarih alanı, anahtar/değer tablosu, şablon çubuğu ve karşılaştırma penceresi.
- `pdfmeta/templates.py`: şablonların JSON dosyasında saklanması.
- `pdfmeta/theme.py` + `pdfmeta/assets/`: marka renkleri, stil sayfası, logo ve uygulama ikonu.
- `pdfmeta/signing.py`: sertifika üretimi, imza deposu ve PDF imzalama (pyHanko).
- `pdfmeta/sign_ui.py`: Dijital İmza sekmesi ve İmzala çubuğu.
- `pdfmeta/multi.py`: Online Düzenleme sekmesi.
- `pdfmeta/preview.py`: uygulama içi PDF önizleme penceresi (QtPdf).
- `pdfmeta/compress.py` + `pdfmeta/compress_ui.py`: PDF küçültme motoru ve sekmesi.
- `pdfmeta/reader.py` + `pdfmeta/reader_ui.py`: belge okuyucu motoru ve sekmesi.
- `pdfmeta/ui.py`: ana pencere, tek dosya ve toplu düzenleme sekmeleri.
- `main.py`: giriş noktası.
