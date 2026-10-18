import React from 'react';
import { chapterStatusColors } from '../../constants';

/**
 * Chapter list with per-chapter actions: Preview / Export (completed
 * chapters) and Retry / Redownload (downloaded books only).
 * Presentational: the parent performs the API calls.
 *
 * @param {object} props
 * @param {object[]} props.chapters - chapter rows (id, chapter_order, chapter_title, download_status)
 * @param {boolean} props.translated - translated book? (hides per-chapter download)
 * @param {(chapterId: number) => void} props.onPreview
 * @param {(chapterId: number) => void} props.onExport
 * @param {(chapterId: number) => void} props.onDownload
 */
const ChapterTable = ({ chapters, translated, onPreview, onExport, onDownload }) => (
  <div className="bg-white rounded-lg shadow overflow-hidden">
    <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
      <h2 className="text-lg font-semibold">Chapters</h2>
      <span className="text-sm text-gray-500">{chapters.length} total</span>
    </div>
    <table className="w-full">
      <thead>
        <tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
          <th className="px-6 py-4 w-16">#</th>
          <th className="px-6 py-4">Title</th>
          <th className="px-6 py-4 w-32">Status</th>
          <th className="px-6 py-4">Action</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200">
        {chapters.length === 0 && (
          <tr><td colSpan={4} className="px-6 py-12 text-center text-gray-400">No chapters extracted yet.</td></tr>
        )}
        {chapters.map(ch => (
          <tr key={ch.id} className="hover:bg-gray-50 transition">
            <td className="px-6 py-3 text-sm text-gray-500">{ch.chapter_order}</td>
            <td className="px-6 py-3 text-sm text-gray-900">{ch.chapter_title}</td>
            <td className="px-6 py-3">
              <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${chapterStatusColors[ch.download_status] || 'bg-gray-100 text-gray-700'}`}>
                {ch.download_status}
              </span>
            </td>
            <td className="px-6 py-3">
              {ch.download_status === 'completed' && (
                <>
                  <button onClick={() => onPreview(ch.id)}
                    className="text-xs bg-emerald-100 hover:bg-emerald-200 text-emerald-700 px-2 py-1 rounded transition">
                    Preview
                  </button>
                  <button onClick={() => onExport(ch.id)}
                    className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-1 rounded transition ml-1">
                    Export
                  </button>
                </>
              )}
              {/* Per-chapter (re)download exists only for scraped books, not translated ones. */}
              {!translated && ch.download_status === 'failed' && (
                <button onClick={() => onDownload(ch.id)}
                  className="text-xs bg-orange-100 hover:bg-orange-200 text-orange-700 px-2 py-1 rounded transition">
                  Retry
                </button>
              )}
              {!translated && ch.download_status === 'completed' && (
                <button onClick={() => onDownload(ch.id)}
                  className="text-xs bg-purple-100 hover:bg-purple-200 text-purple-700 px-2 py-1 rounded transition ml-1">
                  Redownload
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default ChapterTable;
