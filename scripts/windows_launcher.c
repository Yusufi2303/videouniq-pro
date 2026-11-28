#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <wchar.h>

/*
 * Do not use swprintf/wprintf with %s to build paths.
 * MinGW's C99 swprintf treats %s as char*, so a wchar_t* from
 * GetModuleFileNameW is read as "C" then NUL (C:\...) and the
 * launcher looks for C\python\pythonw.exe instead of <exe_dir>\python\.
 *
 * Launch python.exe (not pythonw) with redirected stdout/stderr so a
 * missing module or Qt plugin prints into a log and a MessageBox,
 * instead of failing silently under CREATE_NO_WINDOW.
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
    /* Prefer python.exe so redirected stderr actually captures a traceback. */
    static const wchar_t *rel[] = {
        L"python\\python.exe",
        L"python\\pythonw.exe",
        L"python.exe",
        L"pythonw.exe",
    };
    unsigned i;
    for (i = 0; i < sizeof(rel) / sizeof(rel[0]); i++) {
        if (join2(out, cap, root, rel[i]) && file_ok(out)) {
            return 1;
        }
    }
    return 0;
}

static int require_file(const wchar_t *root, const wchar_t *rel, wchar_t *msg, size_t cap) {
    wchar_t path[PATH_BUF];
    if (!join2(path, PATH_BUF, root, rel) || !file_ok(path)) {
        msg[0] = 0;
        wappend(msg, cap, L"Не найден файл:\n");
        wappend(msg, cap, root);
        wappend(msg, cap, L"\\");
        wappend(msg, cap, rel);
        wappend(msg, cap, L"\n\nРаспакуйте полную папку VideoUniqPro (python, src, vendor).");
        return 0;
    }
    return 1;
}

static int make_log_path(const wchar_t *root, wchar_t *out, size_t cap) {
    wchar_t base[PATH_BUF];
    wchar_t dir[PATH_BUF];
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", base, PATH_BUF);
    if (n > 0 && n < PATH_BUF) {
        if (join2(dir, PATH_BUF, base, L"VideoUniqPro")) {
            CreateDirectoryW(dir, NULL);
            if (join2(out, cap, dir, L"launch.log")) {
                return 1;
            }
        }
    }
    return join2(out, cap, root, L"VideoUniqPro-launch.log");
}

static HANDLE open_log(const wchar_t *path) {
    SECURITY_ATTRIBUTES sa;
    HANDLE h;
    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    h = CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ,
        &sa,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (h == INVALID_HANDLE_VALUE) {
        return INVALID_HANDLE_VALUE;
    }
    SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    return h;
}

static void show_log_error(DWORD code, const wchar_t *logpath) {
    wchar_t msg[PATH_BUF];
    wchar_t tailw[2400];
    char tail[1600];
    HANDLE h;
    DWORD got = 0;
    LARGE_INTEGER size;
    DWORD to_read;
    DWORD converted;

    msg[0] = 0;
    wappend(msg, PATH_BUF, L"VideoUniq Pro не открыл окно (код ");
    {
        wchar_t num[16];
        unsigned v = (unsigned)code;
        int i = 0;
        wchar_t tmp[16];
        int n = 0;
        if (v == 0) {
            num[0] = L'0';
            num[1] = 0;
        } else {
            while (v && n < 10) {
                tmp[n++] = (wchar_t)(L'0' + (v % 10));
                v /= 10;
            }
            while (n) {
                num[i++] = tmp[--n];
            }
            num[i] = 0;
        }
        wappend(msg, PATH_BUF, num);
    }
    wappend(msg, PATH_BUF, L").\n\nЖурнал:\n");
    wappend(msg, PATH_BUF, logpath);
    wappend(msg, PATH_BUF, L"\n\n");

    tailw[0] = 0;
    h = CreateFileW(logpath, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        size.QuadPart = 0;
        if (GetFileSizeEx(h, &size) && size.QuadPart > 0) {
            to_read = (DWORD)sizeof(tail) - 1;
            if (size.QuadPart > (LONGLONG)to_read) {
                LARGE_INTEGER pos;
                pos.QuadPart = size.QuadPart - (LONGLONG)to_read;
                SetFilePointerEx(h, pos, NULL, FILE_BEGIN);
            }
            if (ReadFile(h, tail, to_read, &got, NULL) && got > 0) {
                tail[got] = 0;
                converted = MultiByteToWideChar(CP_UTF8, 0, tail, (int)got, tailw, 2399);
                if (converted <= 0) {
                    converted = MultiByteToWideChar(CP_ACP, 0, tail, (int)got, tailw, 2399);
                }
                if (converted > 0) {
                    tailw[converted] = 0;
                }
            }
        }
        CloseHandle(h);
    }
    if (tailw[0]) {
        wappend(msg, PATH_BUF, tailw);
    } else {
        wappend(
            msg,
            PATH_BUF,
            L"В журнале нет текста. Частая причина: python*._pth без ../src "
            L"(PYTHONPATH игнорируется) или нет qwindows.dll / VC++ runtime."
        );
    }
    die(msg);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrev, LPSTR lpCmd, int nShow) {
    wchar_t exe[PATH_BUF];
    wchar_t python[PATH_BUF];
    wchar_t ffmpeg[PATH_BUF];
    wchar_t pyhome[PATH_BUF];
    wchar_t srcdir[PATH_BUF];
    wchar_t boot[PATH_BUF];
    wchar_t pyside[PATH_BUF];
    wchar_t shiboken[PATH_BUF];
    wchar_t qtplug[PATH_BUF];
    wchar_t qpa[PATH_BUF];
    wchar_t oldpath[PATH_BUF];
    wchar_t newpath[PATH_BUF];
    wchar_t extra[2048];
    wchar_t cmdline[PATH_BUF];
    wchar_t msg[PATH_BUF];
    wchar_t logpath[PATH_BUF];
    wchar_t exe_log[PATH_BUF];
    wchar_t *slash;
    const wchar_t *root;
    DWORD n;
    DWORD code;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    HANDLE hLog;
    HANDLE hNull;
    SECURITY_ATTRIBUTES sa;

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
    SetCurrentDirectoryW(root);

    if (!find_python(root, python, PATH_BUF)) {
        msg[0] = 0;
        wappend(msg, PATH_BUF, L"Не найден python.exe / pythonw.exe рядом с программой.\n\nПапка:\n");
        wappend(msg, PATH_BUF, root);
        wappend(msg, PATH_BUF, L"\n\nОжидается:\n");
        wappend(msg, PATH_BUF, root);
        wappend(msg, PATH_BUF, L"\\python\\python.exe\n\nРаспакуйте полную папку VideoUniqPro.");
        die(msg);
        return 1;
    }

    if (!require_file(root, L"boot.py", msg, PATH_BUF) ||
        !require_file(root, L"src\\videouniq\\__main__.py", msg, PATH_BUF) ||
        !require_file(root, L"python\\python312.dll", msg, PATH_BUF) ||
        !require_file(root, L"python\\python312._pth", msg, PATH_BUF) ||
        !require_file(root, L"python\\Lib\\site-packages\\PySide6\\plugins\\platforms\\qwindows.dll", msg, PATH_BUF)) {
        die(msg);
        return 1;
    }

    if (!join2(ffmpeg, PATH_BUF, root, L"vendor\\ffmpeg\\win64") ||
        !join2(pyhome, PATH_BUF, root, L"python") ||
        !join2(srcdir, PATH_BUF, root, L"src") ||
        !join2(boot, PATH_BUF, root, L"boot.py") ||
        !join2(pyside, PATH_BUF, root, L"python\\Lib\\site-packages\\PySide6") ||
        !join2(shiboken, PATH_BUF, root, L"python\\Lib\\site-packages\\shiboken6") ||
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
    wappend(newpath, PATH_BUF, L";");
    wappend(newpath, PATH_BUF, pyside);
    wappend(newpath, PATH_BUF, L";");
    wappend(newpath, PATH_BUF, shiboken);
    if (oldpath[0]) {
        wappend(newpath, PATH_BUF, L";");
        wappend(newpath, PATH_BUF, oldpath);
    }
    SetEnvironmentVariableW(L"PATH", newpath);
    SetEnvironmentVariableW(L"PYTHONPATH", srcdir);
    SetEnvironmentVariableW(L"PYTHONHOME", pyhome);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");
    SetEnvironmentVariableW(L"PYTHONUNBUFFERED", L"1");
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
    wappend(cmdline, PATH_BUF, L"\" -u -X utf8 \"");
    wappend(cmdline, PATH_BUF, boot);
    wappend(cmdline, PATH_BUF, L"\"");
    if (extra[0]) {
        wappend(cmdline, PATH_BUF, L" ");
        wappend(cmdline, PATH_BUF, extra);
    }

    if (!make_log_path(root, logpath, PATH_BUF)) {
        die(L"Не удалось создать журнал запуска.");
        return 1;
    }
    hLog = open_log(logpath);
    if (hLog == INVALID_HANDLE_VALUE) {
        if (!join2(logpath, PATH_BUF, root, L"VideoUniqPro-launch.log")) {
            die(L"Не удалось открыть журнал запуска.");
            return 1;
        }
        hLog = open_log(logpath);
    }
    if (hLog == INVALID_HANDLE_VALUE) {
        die(L"Не удалось открыть журнал запуска.");
        return 1;
    }

    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    hNull = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);

    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = (hNull == INVALID_HANDLE_VALUE) ? GetStdHandle(STD_INPUT_HANDLE) : hNull;
    si.hStdOutput = hLog;
    si.hStdError = hLog;

    if (!CreateProcessW(
            python,
            cmdline,
            NULL,
            NULL,
            TRUE,
            CREATE_NO_WINDOW,
            NULL,
            root,
            &si,
            &pi
        )) {
        CloseHandle(hLog);
        if (hNull != INVALID_HANDLE_VALUE) {
            CloseHandle(hNull);
        }
        msg[0] = 0;
        wappend(msg, PATH_BUF, L"Не удалось запустить:\n");
        wappend(msg, PATH_BUF, python);
        die(msg);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    FlushFileBuffers(hLog);
    CloseHandle(hLog);
    if (hNull != INVALID_HANDLE_VALUE) {
        CloseHandle(hNull);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    if (join2(exe_log, PATH_BUF, root, L"VideoUniqPro-launch.log")) {
        CopyFileW(logpath, exe_log, FALSE);
    }

    if (code != 0) {
        show_log_error(code, logpath);
    }
    return (int)code;
}
