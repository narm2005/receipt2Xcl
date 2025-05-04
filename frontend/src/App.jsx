import React, { useState } from "react";
import axios from "axios";

export default function ReceiptUploader() {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [results, setResults] = useState([]);

  const handleFileChange = (event) => {
    setFiles(event.target.files);
  };

  const handleUpload = async (event) => {
    event.preventDefault();
    if (!files.length) {
      setMessage("Please select at least one file.");
      return;
    }

    const formData = new FormData();
    for (let file of files) {
      formData.append("files", file);
    }

    setUploading(true);
    setMessage("");

    try {
      const response = await axios.post("http://localhost:8000/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setMessage("Upload and processing successful. See results below.");
      setResults(response.data.results);
      console.log("Server response:", response.data);
    } catch (error) {
      setMessage("Upload failed. See console for error.");
      console.error("Upload error:", error);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-4 max-w-xl mx-auto">
      <h2 className="text-2xl font-semibold mb-4">Upload Receipt Images</h2>
      <form onSubmit={handleUpload} className="space-y-4">
        <input
          type="file"
          name="files"
          accept="image/*"
          multiple
          onChange={handleFileChange}
          className="block w-full"
        />
        <button
          type="submit"
          disabled={uploading}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          {uploading ? "Uploading..." : "Upload"}
        </button>
      </form>
      {message && <p className="mt-4 text-sm text-gray-700">{message}</p>}
      {results.length > 0 && (
        <div className="mt-6">
          <h3 className="text-xl font-medium mb-2">AI Parsed Results:</h3>
          <ul className="space-y-2">
            {results.map((res, index) => (
              <li key={index} className="bg-gray-100 p-2 rounded">
                <strong>{res.filename}</strong>: <pre className="whitespace-pre-wrap">{res.parsed}</pre>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
