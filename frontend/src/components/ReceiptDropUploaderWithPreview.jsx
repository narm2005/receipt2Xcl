import React, { useState } from "react";
import "../styles/ReceiptDropUploaderWithPreview.css";


const ReceiptDropUploaderWithPreview = ({ onUploadToServer }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState([]);
  const [convertedData, setConvertedData] = useState([]);

  const handleDrop = async (e) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFiles = Array.from(e.dataTransfer.files);
    await handleFilesUpload(droppedFiles);
  };

  const handleBrowse = async (e) => {
    const selected = Array.from(e.target.files);
    await handleFilesUpload(selected);
  };

  const handleFilesUpload = async (selectedFiles) => {
    setFiles(selectedFiles);

    const formData = new FormData();
    formData.append('files', files); // 'files' matches FastAPI
    if (selectedFiles.length === 0) {
      setConvertedData({ error: "No files selected." });
      return;
    }
    selectedFiles.forEach((file) => formData.append("files", file));

    try {
          const res = await fetch("http://localhost:8000/upload", { 
          method: "POST",
        body: formData,
      });
      const result = await res.json();
      if (result?.excel_url) {
        setConvertedData(result); // assume structured JSON or add formatting logic
      } else {
        setConvertedData({ error: "No converted data returned." });
      }
    } catch (error) {
      setConvertedData({ error: "Upload failed." });
    }
  };

  return (
    <div className="receipt-uploader-container">
      {/* Left Panel */}
      <div
        className={`left-panel ${isDragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <p>📤 Drag & Drop files or</p>
        <label className="browse-button">
          Browse
          <input type="file" multiple onChange={handleBrowse} />
        </label>

        {files.length > 0 && (
          <ul className="file-list">
            {files.map((file, idx) => (
              <li key={idx}>{file.name}</li>
            ))}
          </ul>
        )}
      </div>

      {/* Right Panel */}
      <div className="right-panel">
        <h3>Converted Receipt Data</h3>
        <div className="converted-output">
          {convertedData.error ? (
            <p className="error">{convertedData.error}</p>
          ) : convertedData.total_items ? (
            <pre>{JSON.stringify(convertedData, null, 2)}</pre>
          ) : (
            <p>No converted data yet.</p>
          )}
        </div>
      </div>
    </div>
  );
};
export default ReceiptDropUploaderWithPreview;
