#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static void die(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"VideoUniq Pro", MB_OK | MB_ICONERROR);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrev, LPSTR lpCmd, int nShow) {
    (void)hInstance;
    (void)hPrev;
    (void)nShow;

    wchar_t exe[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exe, MAX_PATH)) {
        die(L"Не удалось определить путь к VideoUniqPro.exe");
        return 1;
    }
    wchar_t *slash = wcsrchr(exe, L'\\');
    if (!slash) {
        die(L"Некорректный путь к программе");
        return 1;
    }
    *slash = 0;
    const wchar_t *root = exe;

    wchar_t pythonw[MAX_PATH];
    swprintf(pythonw, MAX_PATH, L"%s\\python\\pythonw.exe", root);
    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES) {
        swprintf(pythonw, MAX_PATH, L"%s\\python\\python.exe", root);
    }
    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES) {
        die(L"Не найден pythonw.exe. Распакуйте полную папку VideoUniqPro.");
        return 1;
    }

    wchar_t oldpath[32767];
    DWORD n = GetEnvironmentVariableW(L"PATH", oldpath, 32767);
    if (n == 0 || n >= 32767) {
        oldpath[0] = 0;
    }
    wchar_t newpath[32767];
    swprintf(
        newpath,
        32767,
        L"%s\\vendor\\ffmpeg\\win64;%s\\python;%s",
        root,
        root,
        oldpath
    );
    SetEnvironmentVariableW(L"PATH", newpath);

    wchar_t pypath[MAX_PATH * 2];
    swprintf(pypath, MAX_PATH * 2, L"%s\\src", root);
    SetEnvironmentVariableW(L"PYTHONPATH", pypath);
    wchar_t pyhome[MAX_PATH];
    swprintf(pyhome, MAX_PATH, L"%s\\python", root);
    SetEnvironmentVariableW(L"PYTHONHOME", pyhome);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");

    wchar_t qtplug[MAX_PATH * 2];
    swprintf(qtplug, MAX_PATH * 2, L"%s\\python\\Lib\\site-packages\\PySide6\\plugins", root);
    SetEnvironmentVariableW(L"QT_PLUGIN_PATH", qtplug);
    wchar_t qpa[MAX_PATH * 2];
    swprintf(qpa, MAX_PATH * 2, L"%s\\python\\Lib\\site-packages\\PySide6\\plugins\\platforms", root);
    SetEnvironmentVariableW(L"QT_QPA_PLATFORM_PLUGIN_PATH", qpa);

    wchar_t extra[2048];
    extra[0] = 0;
    if (lpCmd && lpCmd[0]) {
        MultiByteToWideChar(CP_ACP, 0, lpCmd, -1, extra, 2048);
    }

    wchar_t cmdline[32768];
    if (extra[0]) {
        swprintf(cmdline, 32768, L"\"%s\" -m videouniq %s", pythonw, extra);
    } else {
        swprintf(cmdline, 32768, L"\"%s\" -m videouniq", pythonw);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    if (!CreateProcessW(
            pythonw,
            cmdline,
            NULL,
            NULL,
            FALSE,
            CREATE_NO_WINDOW,
            NULL,
            root,
            &si,
            &pi
        )) {
        die(L"Не удалось запустить pythonw.exe");
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
