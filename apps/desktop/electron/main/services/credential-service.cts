import { Buffer } from "node:buffer"
import { spawn } from "node:child_process"

const CREDENTIAL_TARGET_PREFIX = "AITranslator/ai"
const MAX_LLM_API_KEY_BYTES = 4096
const MAX_HELPER_OUTPUT_BYTES = 1024 * 1024

const SUPPORTED_PROVIDERS = new Set([
  "deepseek",
  "openai",
  "google",
  "mistral",
  "groq",
  "openrouter",
  "together",
  "qwen",
  "openai_compatible",
])

const WINDOWS_CREDENTIAL_SCRIPT = String.raw\`
$ErrorActionPreference = "Stop"

$source = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

public static class AITransCredentialManager
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct CREDENTIAL
    {
        public UInt32 Flags;
        public UInt32 Type;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string TargetName;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string Comment;
        public FILETIME LastWritten;
        public UInt32 CredentialBlobSize;
        public IntPtr CredentialBlob;
        public UInt32 Persist;
        public UInt32 AttributeCount;
        public IntPtr Attributes;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string TargetAlias;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(
        string target,
        UInt32 type,
        UInt32 flags,
        out IntPtr credential);

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWrite(
        ref CREDENTIAL credential,
        UInt32 flags);

    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDelete(
        string target,
        UInt32 type,
        UInt32 flags);

    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr credential);

    public static byte[] Read(string target)
    {
        IntPtr credentialPointer;
        if (!CredRead(target, 1, 0, out credentialPointer))
        {
            int error = Marshal.GetLastWin32Error();
            if (error == 1168)
            {
                return null;
            }
            throw new Win32Exception(error, "CredReadW failed.");
        }

        try
        {
            CREDENTIAL credential = Marshal.PtrToStructure<CREDENTIAL>(credentialPointer);
            if (credential.CredentialBlob == IntPtr.Zero || credential.CredentialBlobSize == 0)
            {
                return new byte[0];
            }

            byte[] bytes = new byte[credential.CredentialBlobSize];
            Marshal.Copy(credential.CredentialBlob, bytes, 0, bytes.Length);
            return bytes;
        }
        finally
        {
            CredFree(credentialPointer);
        }
    }

    public static void Write(string target, string username, string secret)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(secret);
        IntPtr blob = IntPtr.Zero;

        try
        {
            if (bytes.Length > 0)
            {
                blob = Marshal.AllocCoTaskMem(bytes.Length);
                Marshal.Copy(bytes, 0, blob, bytes.Length);
            }

            CREDENTIAL credential = new CREDENTIAL
            {
                Type = 1,
                TargetName = target,
                CredentialBlobSize = (UInt32)bytes.Length,
                CredentialBlob = blob,
                Persist = 2,
                UserName = username
            };

            if (!CredWrite(ref credential, 0))
            {
                int error = Marshal.GetLastWin32Error();
                throw new Win32Exception(error, "CredWriteW failed.");
            }
        }
        finally
        {
            if (blob != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(blob);
            }
        }
    }

    public static void Delete(string target)
    {
        if (CredDelete(target, 1, 0))
        {
            return;
        }

        int error = Marshal.GetLastWin32Error();
        if (error != 1168)
        {
            throw new Win32Exception(error, "CredDeleteW failed.");
        }
    }
}
'@

$null = Add-Type -TypeDefinition $source -Language CSharp

try {
    $requestText = [Console]::In.ReadToEnd()
    $request = $requestText | ConvertFrom-Json

    switch ([string]$request.action) {
        "status" {
            $bytes = [AITransCredentialManager]::Read([string]$request.target)
            $result = @{
                ok = $true
                found = ($null -ne $bytes -and $bytes.Length -gt 0)
            }
        }
        "read" {
            $bytes = [AITransCredentialManager]::Read([string]$request.target)
            $result = @{
                ok = $true
                found = ($null -ne $bytes -and $bytes.Length -gt 0)
                blob = if ($null -eq $bytes) { "" } else { [Convert]::ToBase64String($bytes) }
            }
        }
        "save" {
            [AITransCredentialManager]::Write(
                [string]$request.target,
                [string]$request.provider,
                [string]$request.secret
            )
            $result = @{ ok = $true }
        }
        "delete" {
            [AITransCredentialManager]::Delete([string]$request.target)
            $result = @{ ok = $true }
        }
        default {
            throw "Unsupported credential helper action."
        }
    }

    [Console]::Out.Write(($result | ConvertTo-Json -Compress))
}
catch {
    $message = if ($_.Exception.Message) { $_.Exception.Message } else { "Credential helper failed." }
    [Console]::Out.Write((@{ ok = $false; error = $message } | ConvertTo-Json -Compress))
    exit 1
}
\`

type CredentialAction = "status" | "read" | "save" | "delete"

interface CredentialHelperRequest {
  action: CredentialAction
  target: string
  provider: string
  secret?: string
}

interface CredentialHelperResponse {
  ok: boolean
  found?: boolean
  blob?: string
  error?: string
}

export interface CredentialStatus {
  configured: boolean
}

export interface CredentialPreview extends CredentialStatus {
  masked: string
}

export function normalizeCredentialProvider(provider: string): string {
  const normalized = provider.trim().toLowerCase().replaceAll("-", "_")
  if (!SUPPORTED_PROVIDERS.has(normalized)) {
    throw new Error("Unsupported AI provider credential namespace.")
  }
  return normalized
}

function credentialTarget(provider: string): string {
  return \`\${CREDENTIAL_TARGET_PREFIX}/\${normalizeCredentialProvider(provider)}\`
}

export function decodeCredentialBlob(blob: string): string {
  const bytes = Buffer.from(blob, "base64")
  if (bytes.length === 0) return ""

  const utf8 = bytes.toString("utf8").replace(/\u0000+$/g, "")
  if (!utf8.includes("\u0000") && !utf8.includes("\uFFFD")) {
    return utf8
  }

  if (bytes.length % 2 === 0) {
    return bytes.toString("utf16le").replace(/\u0000+$/g, "")
  }

  throw new Error("Stored AI credential could not be decoded.")
}

function maskCredential(secret: string): string {
  const characters = Array.from(secret.trim())
  if (characters.length === 0) return ""

  const suffix = characters.slice(-4).join("")
  const hiddenCount = Math.min(12, Math.max(4, characters.length - suffix.length))
  return \`\${"•".repeat(hiddenCount)}\${suffix} · \${characters.length} chars\`
}

function runWindowsCredentialHelper(
  request: CredentialHelperRequest,
): Promise<CredentialHelperResponse> {
  if (process.platform !== "win32") {
    return Promise.reject(
      new Error("Desktop credential storage is currently available only on Windows."),
    )
  }

  const encodedCommand = Buffer
    .from(WINDOWS_CREDENTIAL_SCRIPT, "utf16le")
    .toString("base64")

  return new Promise((resolve, reject) => {
    const child = spawn(
      "powershell.exe",
      [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encodedCommand,
      ],
      {
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      },
    )

    let stdout = ""
    let stderr = ""
    let outputBytes = 0
    let settled = false

    const fail = (error: unknown) => {
      if (settled) return
      settled = true
      reject(error)
    }

    const append = (current: string, chunk: Buffer): string => {
      outputBytes += chunk.length
      if (outputBytes > MAX_HELPER_OUTPUT_BYTES) {
        child.kill()
        fail(new Error("Credential helper output exceeded the safety limit."))
        return current
      }
      return current + chunk.toString("utf8")
    }

    child.stdout.on("data", (chunk: Buffer) => {
      stdout = append(stdout, chunk)
    })

    child.stderr.on("data", (chunk: Buffer) => {
      stderr = append(stderr, chunk)
    })

    child.once("error", fail)
    child.once("exit", (code) => {
      if (settled) return

      let response: CredentialHelperResponse | null = null
      try {
        response = JSON.parse(stdout.trim()) as CredentialHelperResponse
      } catch {
        // Fall through to a generic error without including secret-bearing input.
      }

      if (code !== 0 || !response?.ok) {
        fail(
          new Error(
            response?.error ||
            stderr.trim() ||
            "Windows Credential Manager operation failed.",
          ),
        )
        return
      }

      settled = true
      resolve(response)
    })

    child.stdin.end(JSON.stringify(request))
  })
}

export async function getCredentialStatus(
  provider: string,
): Promise<CredentialStatus> {
  const normalized = normalizeCredentialProvider(provider)
  const response = await runWindowsCredentialHelper({
    action: "status",
    target: credentialTarget(normalized),
    provider: normalized,
  })
  return { configured: Boolean(response.found) }
}

export async function getCredentialPreview(
  provider: string,
): Promise<CredentialPreview> {
  const normalized = normalizeCredentialProvider(provider)
  const response = await runWindowsCredentialHelper({
    action: "read",
    target: credentialTarget(normalized),
    provider: normalized,
  })

  if (!response.found || !response.blob) {
    return { configured: false, masked: "" }
  }

  const secret = decodeCredentialBlob(response.blob).trim()
  return {
    configured: Boolean(secret),
    masked: maskCredential(secret),
  }
}

export async function saveCredential(
  provider: string,
  apiKey: string,
): Promise<void> {
  const normalized = normalizeCredentialProvider(provider)
  const secret = apiKey.trim()
  if (!secret) {
    throw new Error("API Key must not be empty.")
  }
  if (Buffer.byteLength(secret, "utf8") > MAX_LLM_API_KEY_BYTES) {
    throw new Error("API Key is too long.")
  }

  await runWindowsCredentialHelper({
    action: "save",
    target: credentialTarget(normalized),
    provider: normalized,
    secret,
  })
}

export async function deleteCredential(provider: string): Promise<void> {
  const normalized = normalizeCredentialProvider(provider)
  await runWindowsCredentialHelper({
    action: "delete",
    target: credentialTarget(normalized),
    provider: normalized,
  })
}
