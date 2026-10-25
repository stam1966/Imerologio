; Εγκατάσταση «Πρόγραμμα Δράσεων Σχολείου» (Inno Setup 6). Χτίζεται στο GitHub Actions:
;   iscc /DAppVersion=2.0.0 /DSourceDir=..\dist\Programma_Draseon installer\pds.iss
; Ένα Setup.exe για Windows 64-bit και 32-bit: εγκαθίσταται το αντίστοιχο runtime.
; Τα δεδομένα του σχολείου ΔΕΝ βρίσκονται στον φάκελο της εφαρμογής (Έγγραφα\Πρόγραμμα Δράσεων Σχολείου)
; και δεν αγγίζονται ποτέ από εγκατάσταση, ενημέρωση ή απεγκατάσταση.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Programma_Draseon"
#endif
#define AppName "Πρόγραμμα Δράσεων Σχολείου"

[Setup]
AppId={{34019F59-4D5B-4BB1-8694-8969F870D7DE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Σταμάτης Κοκολόγος
AppPublisherURL=https://github.com/stam1966/Imerologio
AppSupportURL=https://github.com/stam1966/Imerologio/issues
AppUpdatesURL=https://github.com/stam1966/Imerologio/releases
DefaultDirName={localappdata}\Programs\ProgrammaDraseon
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Programma_Draseon_Setup_{#AppVersion}
SetupIconFile=..\src\app.ico
UninstallDisplayIcon={app}\src\app.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=6.3
CloseApplications=force
RestartApplications=no

[Languages]
#ifexist AddBackslash(SourcePath) + "Greek.isl"
Name: "el"; MessagesFile: "{#SourcePath}\Greek.isl"
#else
Name: "el"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "Εικονίδιο στην επιφάνεια εργασίας"; GroupDescription: "Εικονίδια:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\runtime-x64,\runtime-x86,\shared_data_path.txt,\Dedomena,\tools,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\runtime-x64\*"; DestDir: "{app}\runtime"; Check: Is64BitInstallMode; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\runtime-x86\*"; DestDir: "{app}\runtime"; Check: not Is64BitInstallMode; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-X utf8 ""{app}\src\server.py"""; WorkingDir: "{app}"; IconFilename: "{app}\src\app.ico"
Name: "{group}\{#AppName} (διάγνωση προβλημάτων)"; Filename: "{app}\START_KONSOLA.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\src\app.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-X utf8 ""{app}\src\server.py"""; WorkingDir: "{app}"; IconFilename: "{app}\src\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-X utf8 ""{app}\src\server.py"""; WorkingDir: "{app}"; Description: "Άνοιγμα της εφαρμογής"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; παλιά αρχεία κώδικα από προηγούμενη έκδοση (τα δεδομένα δεν βρίσκονται εδώ)
Type: filesandordirs; Name: "{app}\src\__pycache__"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{localappdata}\ProgrammaDraseon\window"

[Messages]
el.FinishedLabel=Η εγκατάσταση ολοκληρώθηκε. Η εφαρμογή ανοίγει από το εικονίδιο «Πρόγραμμα Δράσεων Σχολείου». Τα δεδομένα σας φυλάσσονται στα Έγγραφα (φάκελος «Πρόγραμμα Δράσεων Σχολείου») και διατηρούνται σε ενημερώσεις και απεγκατάσταση.
