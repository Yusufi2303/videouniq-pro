#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <wchar.h>

/*
 * Do not use swprintf/wprintf with %s to build paths.
 * MinGW's C99 swprintf treats %s as char*, so a wchar_t* from
 * GetModuleFileNameW is read as "C" then NUL (C:\...) and the
 * launcher looks for C\python\pythonw.exe instead of <exe_dir>\python\.
 */

#define PATH_BUF 32768

static void die(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"VideoUniq Pro", MB_OK | MB_ICONERROR);
}

static void wappend(wchar_t *dst, size_t cap, const wchar_t *s) {
    size_t n;
    size_t m;
    if (!dst || cap == 0) {
        return;
    }
    n = wcslen(dst);
    if (!s || n + 1 >= cap) {
        return;
    }
    m = wcslen(s);
    if (n + m + 1 > cap) {
        m = cap - n - 1;
    }
    memcpy(dst + n, s, m * sizeof(wchar_t));
    dst[n + m] = 0;
}

static int join2(wchar_t *dst, size_t cap, const wchar_t *a, const wchar_t *b) {
    size_t na;
    size_t nb;
    int slash;
    if (!dst || cap < 2 || !a || !b) {
        return 0;
    }
    na = wcslen(a);
    nb = wcslen(b);
    slash = (na > 0 && a[na - 1] != L'\\' && a[na - 1] != L'/');
    if (na + (slash ? 1u : 0u) + nb + 1u > cap) {
        return 0;
    }
    memcpy(dst, a, na * sizeof(wchar_t));
    if (slash) {
        dst[na++] = L'\\';
    }
    memcpy(dst + na, b, (nb + 1) * sizeof(wchar_t));
    return 1;
}

static int file_ok(const wchar_t *path) {
    DWORD attr;
    if (!path || !path[0]) {
        return 0;
    }
    attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

static wchar_t *last_sep(wchar_t *p) {
    wchar_t *a;
    wchar_t *b;
    if (!p) {
        return NULL;
    }
    a = wcsrchr(p, L'\\');
    b = wcsrchr(p, L'/');
    if (!a) {
        return b;
    }
    if (!b) {
        return a;
    }
    return a > b ? a : b;
}

static int find_python(const wchar_t *root, wchar_t *out, size_t cap) {
    static const wchar_t *rel[] = {
        L"python\\pythonw.exe",
        L"python\\python.exe",
        L"pythonw.exe",
        L"python.exe",
    };
    unsigned i;
    for (i = 0; i < sizeof(rel) / sizeof(rel[0]); i++) {
        if (join2(out, cap, root, rel[i]) && file_ok(out)) {
            return 1;
        }
    }
    return 0;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrev, LPSTR lpCmd, int nShow) {
    wchar_t exe[PATH_BUF];
    wchar_t python[PATH_BUF];
    wchar_t ffmpeg[PATH_BUF];
    wchar_t pyhome[PATH_BUF];
    wchar_t srcdir[PATH_BUF];
    wchar_t qtplug[PATH_BUF];
    wchar_t qpa[PATH_BUF];
    wchar_t oldpath[PATH_BUF];
    wchar_t newpath[PATH_BUF];
    wchar_t extra[2048];
    wchar_t cmdline[PATH_BUF];
    wchar_t msg[PATH_BUF];
    wchar_t *slash;
    const wchar_t *root;
    DWORD n;
    DWORD code;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    (void)hInstance;
    (void)hPrev;
    (void)nShow;

    n = GetModuleFileNameW(NULL, exe, PATH_BUF);
    if (n == 0 || n >= PATH_BUF) {
        die(L"Не удалось определить путь к VideoUniqPro.exe");
        return 1;
    }
    slash = last_sep(exe);
    if (!slash) {
        die(L"Некорректный путь к программе");
        return 1;
    }
    *slash = 0;
    root = exe;

    /* Always start from the exe folder, never the process cwd. */
    SetCurrentDirectoryW(root);

    if (!find_python(root, python, PATH_BUF)) {
        msg[0] = 0;
        wappend(msg, PATH_BUF, L"Не найден pythonw.exe / python.exe рядом с программой.\n\nПапка:\n");
        wappend(msg, PATH_BUF, root);
        wappend(msg, PATH_BUF, L"\n\nОжидается файл:\n");
        wappend(msg, PATH_BUF, root);
        wappend(msg, PATH_BUF, L"\\python\\pythonw.exe\n\nРаспакуйте полную папку VideoUniqPro (python, src, vendor).");
        die(msg);
        return 1;
    }

    if (!join2(ffmpeg, PATH_BUF, root, L"vendor\\ffmpeg\\win64") ||
        !join2(pyhome, PATH_BUF, root, L"python") ||
        !join2(srcdir, PATH_BUF, root, L"src") ||
        !join2(qtplug, PATH_BUF, root, L"python\\Lib\\site-packages\\PySide6\\plugins") ||
        !join2(qpa, PATH_BUF, root, L"python\\Lib\\site-packages\\PySide6\\plugins\\platforms")) {
        die(L"Слишком длинный путь к VideoUniq Pro.");
        return 1;
    }

    n = GetEnvironmentVariableW(L"PATH", oldpath, PATH_BUF);
    if (n == 0 || n >= PATH_BUF) {
        oldpath[0] = 0;
    }
    newpath[0] = 0;
    wappend(newpath, PATH_BUF, ffmpeg);
    wappend(newpath, PATH_BUF, L";");
    wappend(newpath, PATH_BUF, pyhome);
    if (oldpath[0]) {
        wappend(newpath, PATH_BUF, L";");
        wappend(newpath, PATH_BUF, oldpath);
    }
    SetEnvironmentVariableW(L"PATH", newpath);
    SetEnvironmentVariableW(L"PYTHONPATH", srcdir);
    SetEnvironmentVariableW(L"PYTHONHOME", pyhome);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");
    SetEnvironmentVariableW(L"QT_PLUGIN_PATH", qtplug);
    SetEnvironmentVariableW(L"QT_QPA_PLATFORM_PLUGIN_PATH", qpa);

    extra[0] = 0;
    if (lpCmd && lpCmd[0]) {
        MultiByteToWideChar(CP_ACP, 0, lpCmd, -1, extra, 2048);
        extra[2047] = 0;
    }

    cmdline[0] = 0;
    wappend(cmdline, PATH_BUF, L"\"");
    wappend(cmdline, PATH_BUF, python);
    wappend(cmdline, PATH_BUF, L"\" -m videouniq");
    if (extra[0]) {
        wappend(cmdline, PATH_BUF, L" ");
        wappend(cmdline, PATH_BUF, extra);
    }

    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    if (!CreateProcessW(
            python,
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
        msg[0] = 0;
        wappend(msg, PATH_BUF, L"Не удалось запустить:\n");
        wappend(msg, PATH_BUF, python);
        die(msg);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
