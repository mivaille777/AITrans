const path = require("node:path")

const desktopRoot = __dirname
const repoRoot = path.resolve(desktopRoot, "../..")
const stagedBackend = path.join(repoRoot, "build", "electron-resources", "backend")

module.exports = {
  outDir: "out",
  packagerConfig: {
    name: "AITrans",
    executableName: "AITrans",
    icon: path.join(desktopRoot, "resources", "icon.ico"),
    asar: {
      unpackDir: "dist",
    },
    overwrite: true,
    prune: false,
    extraResource: [stagedBackend],
    ignore: [
      /^\/src(?:\/|$)/,
      /^\/electron(?:\/|$)/,
      /^\/scripts(?:\/|$)/,
      /^\/src-tauri(?:\/|$)/,
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
      },
    },
  ],
}
