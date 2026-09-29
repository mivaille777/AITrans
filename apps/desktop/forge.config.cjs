const fs = require("node:fs")
const path = require("node:path")

const desktopRoot = __dirname
const repoRoot = path.resolve(desktopRoot, "../..")
const stagedBackend = path.join(repoRoot, "build", "electron-resources", "backend")
const stagedSandbox = path.join(repoRoot, "build", "electron-resources", "sandbox")
const releaseVersion = fs.readFileSync(path.join(repoRoot, "VERSION"), "utf8").trim()
const updateConfigPath = path.join(repoRoot, "build", "electron-resources", "update-config.json")

const certificateFile = process.env.AITRANS_WINDOWS_CERTIFICATE_FILE?.trim()
const certificatePassword = process.env.AITRANS_WINDOWS_CERTIFICATE_PASSWORD ?? ""
const signingConfigured = Boolean(certificateFile && certificatePassword)
const windowsSign = signingConfigured
  ? {
      certificateFile,
      certificatePassword,
      timestampServer:
        process.env.AITRANS_WINDOWS_TIMESTAMP_SERVER?.trim() ||
        "http://timestamp.digicert.com",
      description: "AITrans",
    }
  : undefined

module.exports = {
  outDir: "out",
  packagerConfig: {
    name: "AITrans",
    executableName: "AITrans",
    appVersion: releaseVersion,
    buildVersion: releaseVersion,
    icon: path.join(desktopRoot, "resources", "icon.ico"),
    asar: {
      unpackDir: "dist",
    },
    overwrite: true,
    prune: false,
    extraResource: [stagedBackend, stagedSandbox, updateConfigPath],
    ...(windowsSign ? { windowsSign } : {}),
    ignore: [
      /^\/src(?:\/|$)/,
      /^\/electron(?:\/|$)/,
      /^\/scripts(?:\/|$)/,
      /^\/public(?:\/|$)/,
      /^\/resources(?:\/|$)/,
      /^\/node_modules(?:\/|$)/,
      /^\/test-results(?:\/|$)/,
      /^\/out(?:\/|$)/,
      /^\/package-lock\.json$/,
      /^\/forge\.config\.cjs$/,
      /^\/tsconfig\..*\.json$/,
      /^\/vite\.config\.ts$/,
      /^\/README\.md$/,
    ],
    win32metadata: {
      CompanyName: "AITrans",
      FileDescription: "AITrans Local-first AI Agent Workspace",
      ProductName: "AITrans",
      InternalName: "AITrans",
      OriginalFilename: "AITrans.exe",
    },
  },
  makers: [
    {
      name: "@electron-forge/maker-squirrel",
      config: {
        name: "AITrans",
        authors: "AITrans Contributors",
        description:
          "Local-first AI Agent workspace for research, knowledge, RAG, and multi-agent workflows.",
        setupIcon: path.join(desktopRoot, "resources", "icon.ico"),
        noMsi: true,
        ...(windowsSign ? { windowsSign } : {}),
      },
    },
  ],
}
