/* Validates NSIS SCM arguments without changing Windows services. */
#define WINADVAPI
#include <windows.h>
#include <winsvc.h>
#include <wchar.h>

static void trace(const wchar_t *message) {
    wchar_t path[2048];
    if (!GetEnvironmentVariableW(L"COMITRANS_FIXTURE_LOG", path, 2048)) return;
    HANDLE file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written;
    WriteFile(file, message, (DWORD)(wcslen(message) * sizeof(wchar_t)), &written, NULL);
    WriteFile(file, L"\r\n", 4, &written, NULL);
    CloseHandle(file);
}

static DWORD state(DWORD replacement) {
    wchar_t path[2048];
    if (!GetEnvironmentVariableW(L"COMITRANS_FIXTURE_STATE", path, 2048)) return 0;
    if (replacement == 0xffffffff) { DeleteFileW(path); return 0; }
    HANDLE file = CreateFileW(path, GENERIC_READ | (replacement ? GENERIC_WRITE : 0),
                             FILE_SHARE_READ, NULL, replacement ? OPEN_ALWAYS : OPEN_EXISTING,
                             FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    DWORD current = 0, count;
    if (replacement) WriteFile(file, &replacement, sizeof(replacement), &count, NULL);
    else ReadFile(file, &current, sizeof(current), &count, NULL);
    CloseHandle(file);
    return replacement ? replacement : current;
}

static BOOL configuration(LPCWSTR binary, LPCWSTR account, DWORD type, DWORD start, DWORD error) {
    wchar_t expected[2048];
    GetEnvironmentVariableW(L"COMITRANS_FIXTURE_BINARY", expected, 2048);
    if (!binary || !account || wcscmp(binary, expected) ||
        wcscmp(account, L"NT AUTHORITY\\LocalService") ||
        type != SERVICE_WIN32_OWN_PROCESS || start != SERVICE_AUTO_START || error != SERVICE_ERROR_NORMAL) {
        trace(L"INVALID CONFIGURATION");
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    trace(binary);
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

__declspec(dllexport) SC_HANDLE WINAPI OpenSCManagerW(LPCWSTR machine, LPCWSTR database, DWORD access) {
    if (machine || database || (access != 1 && access != 3)) {
        SetLastError(ERROR_INVALID_PARAMETER); return NULL;
    }
    return (SC_HANDLE)1;
}

__declspec(dllexport) SC_HANDLE WINAPI OpenServiceW(SC_HANDLE manager, LPCWSTR name, DWORD access) {
    if (manager != (SC_HANDLE)1 || !name || (access != 0x24 && access != 0x16 && access != DELETE)) {
        SetLastError(ERROR_INVALID_PARAMETER); return NULL;
    }
    if (!state(0)) { SetLastError(ERROR_SERVICE_DOES_NOT_EXIST); return NULL; }
    return (SC_HANDLE)2;
}

__declspec(dllexport) SC_HANDLE WINAPI CreateServiceW(SC_HANDLE manager, LPCWSTR name, LPCWSTR display,
        DWORD access, DWORD type, DWORD start, DWORD error, LPCWSTR binary, LPCWSTR group,
        LPDWORD tag, LPCWSTR dependencies, LPCWSTR account, LPCWSTR password) {
    if (manager != (SC_HANDLE)1 || !name || !display || access != 0x16 ||
        group || tag || dependencies || password || !configuration(binary, account, type, start, error)) {
        SetLastError(ERROR_INVALID_PARAMETER); return NULL;
    }
    trace(L"create"); state(SERVICE_STOPPED);
    return (SC_HANDLE)2;
}

__declspec(dllexport) BOOL WINAPI ChangeServiceConfigW(SC_HANDLE service, DWORD type, DWORD start,
        DWORD error, LPCWSTR binary, LPCWSTR group, LPDWORD tag, LPCWSTR dependencies,
        LPCWSTR account, LPCWSTR password, LPCWSTR display) {
    if (service != (SC_HANDLE)2 || !display || group || tag || dependencies || password ||
        !configuration(binary, account, type, start, error)) return FALSE;
    trace(L"configure"); return TRUE;
}

__declspec(dllexport) BOOL WINAPI StartServiceW(SC_HANDLE service, DWORD count, LPCWSTR *arguments) {
    if (service != (SC_HANDLE)2 || count || arguments) return FALSE;
    state(SERVICE_RUNNING); trace(L"start"); return TRUE;
}

__declspec(dllexport) BOOL WINAPI QueryServiceStatus(SC_HANDLE service, LPSERVICE_STATUS status) {
    if (service != (SC_HANDLE)2 || !status) return FALSE;
    ZeroMemory(status, sizeof(*status));
    status->dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    status->dwCurrentState = state(0);
    return TRUE;
}

__declspec(dllexport) BOOL WINAPI ControlService(SC_HANDLE service, DWORD control, LPSERVICE_STATUS status) {
    if (service != (SC_HANDLE)2 || control != SERVICE_CONTROL_STOP) return FALSE;
    state(SERVICE_STOPPED); trace(L"stop"); return QueryServiceStatus(service, status);
}

__declspec(dllexport) BOOL WINAPI DeleteService(SC_HANDLE service) {
    if (service != (SC_HANDLE)2) return FALSE;
    state(0xffffffff); trace(L"delete"); return TRUE;
}

__declspec(dllexport) BOOL WINAPI CloseServiceHandle(SC_HANDLE handle) {
    return handle == (SC_HANDLE)1 || handle == (SC_HANDLE)2;
}
