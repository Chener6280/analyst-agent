"use strict";
const path=require('node:path');
const {ZsxqWebError}=require('./core');
const AUDIO=new Set(['.mp3','.m4a','.wav','.aac','.flac','.ogg','.opus','.wma','.amr']);
const VIDEO=new Set(['.mp4','.mov','.mkv','.avi','.webm']);
const DOCUMENTS=new Set(['.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.txt','.html','.md','.rtf','.csv','.png','.jpg','.jpeg','.gif','.webp','.bmp']);
function mediaKind(name){const ext=path.extname(String(name).trim()).toLowerCase();return AUDIO.has(ext)?'audio':VIDEO.has(ext)?'video':DOCUMENTS.has(ext)?'document':'unknown';}
function accepted(item,policy){return item.status==='ok'||policy==='text_non_audio'&&item.status==='deferred'&&['audio','video'].includes(mediaKind(item.original_filename));}
function makeControl(limits,{now=Date.now}={}){
  const started=now(),counts={operations:0,recordsAttempted:0,downloaded:0,reused:0,bytes:0,audioDeferred:0,videoDeferred:0,imagesDeferred:0,metadataOnly:0,unknownDates:0};
  const control={counts,stopped:false,check(){
    if(control.stopped)throw new ZsxqWebError('user_stopped','Stopped by the operator',12);
    if(now()-started>=limits.maxSeconds*1000)throw new ZsxqWebError('time_budget_exhausted','Time budget reached',12);
  },step(){control.check();if(counts.operations>=limits.maxOperations)throw new ZsxqWebError('operation_budget_exhausted','Web action budget reached',12);counts.operations++;},
  topic(){control.check();if(counts.recordsAttempted>=limits.maxRecords)throw new ZsxqWebError('record_budget_exhausted','Topic budget reached',12);counts.recordsAttempted++;},
  file(size){control.check();if(counts.downloaded>=limits.maxFiles)throw new ZsxqWebError('file_budget_exhausted','File budget reached',12);
    if(!Number.isSafeInteger(size)||size<=0)throw new ZsxqWebError('asset_size_unverified','File size is unknown; no download was started',12);
    if(size>limits.maxFileBytes)throw new ZsxqWebError('asset_exceeds_authorized_budget','File exceeds the authorized size',12);
    if(size>limits.maxBytes-counts.bytes)throw new ZsxqWebError('byte_budget_exhausted','Byte budget reached',12);
  }};
  return control;
}
const isPause=code=>code==='user_stopped'||/_budget_exhausted$/.test(code||'');
module.exports={mediaKind,accepted,makeControl,isPause};
