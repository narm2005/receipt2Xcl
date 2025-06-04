// import React, { useState } from 'react';
// import axios from 'axios';
//
// function App() {
//   const [files, setFiles] = useState([]);
//   const [uploading, setUploading] = useState(false);
//   const [result, setResult] = useState(null);
//
//   const handleFileChange = (event) => {
//     const newFiles = Array.from(event.target.files);
//     setFiles(prev => [...prev, ...newFiles]);
//   };
//
//   const handleSubmit = async () => {
//     if (files.length === 0) return;
//
//     const formData = new FormData();
//     files.forEach(file => formData.append('files', file));
//
//     try {
//       setUploading(true);
//       const response = await axios.post('http://localhost:8000/upload', formData);
//       setResult(response.data);
//     } catch (err) {
//       console.error('Upload failed:', err);
//     } finally {
//       setUploading(false);
//     }
//   };
//
//   const downloadExcel = () => {
//     window.open('http://localhost:8000/download', '_blank');
//   };
//
//   return (
//     <div className="min-h-screen bg-gray-50 p-8">
//       <h1 className="text-2xl font-bold mb-4">Receipt to Excel Converter</h1>
//
//       <input
//         type="file"
//         accept="image/*"
//         multiple
//         onChange={handleFileChange}
//         className="mb-4"
//       />
//
//       <div className="mb-4">
//         {files.length > 0 && <p>{files.length} file(s) selected</p>}
//         <button
//           onClick={handleSubmit}
//           className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 mr-4"
//           disabled={uploading}
//         >
//           {uploading ? 'Processing...' : 'Upload & Process'}
//         </button>
//
//         {result && (
//           <button
//             onClick={downloadExcel}
//             className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
//           >
//             Download Excel
//           </button>
//         )}
//       </div>
//
//       {result && (
//         <div className="mt-4 bg-white p-4 rounded shadow">
//           <h2 className="text-lg font-semibold mb-2">Results:</h2>
//           <pre className="whitespace-pre-wrap text-sm">
//             {JSON.stringify(result.results, null, 2)}
//           </pre>
//         </div>
//       )}
//     </div>
//   );
// }
//
// export default App;
import React, { useState } from "react";

function App() {
  const [files, setFiles] = useState([]);
  const [lang, setLang] = useState("");
  const [autoDetect, setAutoDetect] = useState(false);
  const [status, setStatus] = useState("");
  const [downloadReady, setDownloadReady] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (files.length === 0) {
      alert("Please select at least one image.");
      return;
    }

    const formData = new FormData();
    for (let file of files) {
      formData.append("files", file);
    }
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
      } else {
        setStatus(`❌ Error: ${data.detail}`);
      }
    } catch (err) {
      setStatus(`❌ Error: ${err.message}`);
    }
  };

  return (
    <div style={{ maxWidth: 600, margin: "2rem auto", textAlign: "center" }}>
      <h1>📸 Receipts2Excel</h1>
      <p>Upload your receipts and get an AI-parsed Excel file.</p>

      <form onSubmit={handleSubmit}>
        <input
          type="file"
          multiple
          accept="image/*"
          onChange={(e) => setFiles([...e.target.files])}
          required
        />
        <br />
        <select value={lang} onChange={(e) => setLang(e.target.value)}>
          <option value="">Auto-detect</option>
          <option value="eng">English</option>
          <option value="spa">Spanish</option>
          <option value="fra">French</option>
          <option value="deu">German</option>
          <option value="jpn">Japanese</option>
        </select>
        <br />
        <label>
          <input
            type="checkbox"
            checked={autoDetect}
            onChange={(e) => setAutoDetect(e.target.checked)}
          />
          Auto-detect Language
        </label>
        <br />
        <button type="submit">Upload & Convert</button>
      </form>

      <p style={{ marginTop: "20px", fontWeight: "bold" }}>{status}</p>

      {downloadReady && (
        <a
          href="http://localhost:8000/download"
          target="_blank"
          rel="noopener noreferrer"
          style={{ display: "inline-block", marginTop: "1rem", fontWeight: "bold" }}
        >
          ⬇ Download Excel
        </a>
      )}
    </div>
  );
}

export default App;
