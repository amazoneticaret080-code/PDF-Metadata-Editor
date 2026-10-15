; PDF Metadata Düzenleyici - kurulum programı (Inno Setup 6)
; Derlemek için: kurulum_olustur.bat  (önce PyInstaller klasör derlemesi yapar, sonra bu dosyayı derler)
; Python, kütüphaneler ve yazı tipleri uygulama klasörünün içinde gelir; hedef bilgisayara ayrıca bir şey indirilmez.

#define AppName "PDF Metadata Düzenleyici"
#define AppExe "PDFMetadataDuzenleyici.exe"
#define AppVersion "1.0.1"
#define Publisher "Suspend Global"
#ifndef SourceDir
  #define SourceDir "..\build\uygulama\PDFMetadataDuzenleyici"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{7C2E4B1A-5D3F-4E8A-9B6C-2F1D0A9E8B7C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#Publisher}
VersionInfoDescription={#AppName} Kurulumu
; yönetici izni istemez; kullanıcı isterse "tüm kullanıcılar için" seçebilir
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\PDF Metadata Duzenleyici
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=..\pdfmeta\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename=PDFMetadataDuzenleyici_Kurulum_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "PDF dosyalarına sağ tıklayınca 'Birlikte aç' listesine ekle"; GroupDescription: "Diğer:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
; uygulama bu dosyayı görünce çıktıları Belgeler klasörüne kaydeder
Filename: "{app}\kurulum.ini"; Section: "Kurulum"; Key: "Surum"; String: "{#AppVersion}"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; varsayılan PDF programını değiştirmez; yalnızca "Birlikte aç" listesine ekler
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Applications\{#AppExe}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\kurulum.ini"

[Messages]
turkish.WelcomeLabel2=Bu sihirbaz bilgisayarınıza [name/ver] programını kuracak.%n%nGerekli tüm bileşenler (Python, kütüphaneler, yazı tipleri) kurulumun içindedir; internet bağlantısı gerekmez.%n%nDevam etmeden önce diğer uygulamaları kapatmanız önerilir.
