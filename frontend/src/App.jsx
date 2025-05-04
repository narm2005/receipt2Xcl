import React, { useState } from 'react';
import axios from 'axios';

function App() {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  const handleFileChange = (event) => {
    const newFiles = Array.from(event.target.files);
    setFiles(prev => [...prev, ...newFiles]);
  };

  const handleSubmit = async () => {
    if (files.length === 0) return;

    const formData = new FormData();
    files.forEach(file => formData.append('files', file));

    try {
      setUploading(true);
      const response = await axios.post('http://localhost:8000/upload', formData);
      setResult(response.data);
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setUploading(false);
    }
  };

  const downloadExcel = () => {
    window.open('http://localhost:8000/download', '_blank');
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <h1 className="text-2xl font-bold mb-4">Receipt to Excel Converter</h1>

      <input
        type="file"
        accept="image/*"
        multiple
        onChange={handleFileChange}
        className="mb-4"
      />

      <div className="mb-4">
        {files.length > 0 && <p>{files.length} file(s) selected</p>}
        <button
          onClick={handleSubmit}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 mr-4"
          disabled={uploading}
        >
          {uploading ? 'Processing...' : 'Upload & Process'}
        </button>

        {result && (
          <button
            onClick={downloadExcel}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
          >
            Download Excel
          </button>
        )}
      </div>

      {result && (
        <div className="mt-4 bg-white p-4 rounded shadow">
          <h2 className="text-lg font-semibold mb-2">Results:</h2>
          <pre className="whitespace-pre-wrap text-sm">
            {JSON.stringify(result.results, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default App;
