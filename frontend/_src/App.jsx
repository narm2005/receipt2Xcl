import React, { useState } from "react";

function App() {
  const [files, setFiles] = useState([]);
  const [lang, setLang] = useState("");
  const [autoDetect, setAutoDetect] = useState(false);
  const [status, setStatus] = useState("");
  const [downloadReady, setDownloadReady] = useState(false);
  const [result, setResult] = useState(null);

  const handleFileChange = (e) => {
    const selectedFiles = Array.from(e.target.files);
    setFiles((prevFiles) => [...prevFiles, ...selectedFiles]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (files.length === 0) {
      alert("Please select at least one file.");
      return;
    }

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    formData.append("lang", lang);
    formData.append("auto_detect", autoDetect);

    setStatus("⏳ Uploading and processing...");
    setDownloadReady(false);

    try {
      const res = await fetch("http://localhost:8000/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (res.ok) {
        setStatus("✅ Processing complete!");
        setDownloadReady(true);
        setResult(data);
      } else {
        setStatus(`❌ Error: ${data.detail}`);
      }
    } catch (err) {
      setStatus(`❌ Error: ${err.message}`);
    }
  };

  const clearFiles = () => {
    setFiles([]);
    setResult(null);
    setStatus("");
    setDownloadReady(false);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8 text-center">
      <h1 className="text-3xl font-bold mb-4">📊 SlickReceipts.com</h1>
      <p className="mb-6 text-gray-600">
        Upload multiple receipts and download a clean Excel report using AI.
      </p>

      <form
        onSubmit={handleSubmit}
        className="bg-white shadow-md p-6 rounded max-w-xl mx-auto space-y-4"
      >
        <input
          type="file"
          multiple
          accept="image/*,application/pdf"
          onChange={handleFileChange}
          className="block w-full border border-gray-300 p-2 rounded"
        />

        <div className="text-sm text-gray-600">
          {files.length > 0 && (
            <p>{files.length} file(s) selected</p>
          )}
        </div>

        <select
          value={lang}
          onChange={(e) => setLang(e.target.value)}
          className="w-full border border-gray-300 p-2 rounded"
        >
          <option value="">Auto-detect</option>
          <option value="eng">English</option>
          <option value="spa">Spanish</option>
          <option value="fra">French</option>
          <option value="deu">German</option>
          <option value="jpn">Japanese</option>
        </select>

        <label className="flex items-center space-x-2">
          <input
            type="checkbox"
            checked={autoDetect}
            onChange={(e) => setAutoDetect(e.target.checked)}
          />
          <span>Auto-detect Language</span>
        </label>

        <div className="flex justify-center space-x-4">
          <button
            type="submit"
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
          >
            Upload & Convert
          </button>
          <button
            type="button"
            onClick={clearFiles}
            className="bg-gray-300 text-gray-800 px-4 py-2 rounded hover:bg-gray-400"
          >
            Clear
          </button>
        </div>
      </form>

      <p className="mt-6 font-semibold">{status}</p>

      {downloadReady && (
        <a
          href="http://localhost:8000/download"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block mt-4 text-green-700 font-semibold underline"
        >
          ⬇ Download Excel
        </a>
      )}

      {result && (
        <div className="mt-6 bg-white p-4 rounded shadow max-w-xl mx-auto text-left">
          <h2 className="text-lg font-bold mb-2">Parsed Output Preview:</h2>
          <pre className="whitespace-pre-wrap text-sm text-gray-700">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default App;
