'''
svnlog2sqlite.py
Copyright (C) 2009 Nitin Bhide (nitinbhide@gmail.com)

This module is part of SVNPlot (http://code.google.com/p/svnplot) and is released under
the New BSD License: http://www.opensource.org/licenses/bsd-license.php
--------------------------------------------------------------------------------------

python script to convert the Subversion log into an sqlite database
The idea is to use the generated SQLite database as input to Matplot lib for
creating various graphs and analysis. The graphs are inspired from graphs
generated by StatSVN/StatCVS.
'''

import datetime,calendar
import sqlite3
import sys,os
import logging
import traceback
from optparse import OptionParser

import svnlogiter
from svnlogclient import makeunicode

BINARYFILEXT = [ 'doc', 'xls', 'ppt', 'docx', 'xlsx', 'pptx', 'dot', 'dotx', 'ods', 'odm', 'odt', 'ott', 'pdf',
                 'o', 'a', 'obj', 'lib', 'dll', 'so', 'exe',
                 'jar', 'zip', 'z', 'gz', 'tar', 'rar','7z',
                 'pdb', 'idb', 'ilk', 'bsc', 'ncb', 'sbr', 'pch', 'ilk',
                 'bmp', 'dib', 'jpg', 'jpeg', 'png', 'gif', 'ico', 'pcd', 'wmf', 'emf', 'xcf', 'tiff', 'xpm',
                 'gho', 'mp3', 'wma', 'wmv','wav','avi'
                 ]
    
class SVNLog2Sqlite:
    def __init__(self, svnrepopath, sqlitedbpath,verbose=False,**kwargs):
        username=kwargs.pop('username', None)
        password=kwargs.pop('password',None)
        logging.info("Repo url : " + svnrepopath)
        self.svnclient = svnlogiter.SVNLogClient(svnrepopath,BINARYFILEXT,username=username, password=password)
        self.dbpath =sqlitedbpath
        self.dbcon =None
        self.verbose = verbose
        
    def convert(self, svnrevstartdate, svnrevenddate, bUpdLineCount=True, maxtrycount=3):
        #First check if this a full conversion or a partial conversion
        self.initdb()
        self.CreateTables()
        for trycount in range(0, maxtrycount):
            try:
                laststoredrev = self.getLastStoredRev()
                rootUrl = self.svnclient.getRootUrl()
                self.printVerbose("Root url found : %s" % rootUrl)
                (startrevno, endrevno) = self.svnclient.findStartEndRev(svnrevstartdate, svnrevenddate)
                self.printVerbose("Repository Start-End Rev no : %d-%d" % (startrevno, endrevno))
                startrevno = max(startrevno,laststoredrev+1)
                self.ConvertRevs(startrevno, endrevno, bUpdLineCount)
                #every thing is ok. Commit the changes.
                self.dbcon.commit()
            except Exception, expinst:
                logging.exception("Found Error")
                self.svnexception_handler(expinst)
                print "Trying again (%d)" % (trycount+1)            
        
        self.closedb()
        
    def initdb(self):
        self.dbcon = sqlite3.connect(self.dbpath, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
        #self.dbcon.row_factory = sqlite3.Row

    def closedb(self):
        self.dbcon.commit()
        self.dbcon.close()

    def svnexception_handler(self, expinst):
        '''
        decide to continue or exit on the svn exception.
        '''
        self.dbcon.rollback()
        print "Found Error. Rolled back recent changes"
        print "Error type %s" % type(expinst)
        if( isinstance(expinst, AssertionError)):            
            exit(1)            
        exitAdvised = self.svnclient.printSvnErrorHint(expinst)
        if( exitAdvised):
            exit(1)
        
    def getLastStoredRev(self):
        cur = self.dbcon.cursor()
        cur.execute("select max(revno) from svnlog")
        lastStoreRev = 0
        
        row = cur.fetchone()
        if( row != None and len(row) > 0 and row[0] != None):
            lastStoreRev = int(row[0])
        cur.close()
        return(lastStoreRev)

    def getFilePathId(self, filepath, updcur):
        '''
        update the filepath id if required.
        '''
        id = None
        if( filepath ):
            querycur=self.dbcon.cursor()
            querycur.execute('select id from SVNPaths where path = ?', (filepath,))
            resultrow = querycur.fetchone()
            if( resultrow == None):
                updcur.execute('INSERT INTO SVNPaths(path) values(?)', (filepath,))
                querycur.execute('select id from SVNPaths where path = ?', (filepath,))
                resultrow = querycur.fetchone()
            id = resultrow[0]
            querycur.close()
            
        return(id)
    
    def ConvertRevs(self, startrev, endrev, bUpdLineCount):
        self.printVerbose("Converting revisions %d to %d" % (startrev, endrev))
        if( startrev <= endrev):
            self.printVerbose("Conversion started")
            querycur = self.dbcon.cursor()
            updcur = self.dbcon.cursor()
            logging.info("Updating revision from %d to %d" % (startrev, endrev))
            svnloglist = svnlogiter.SVNRevLogIter(self.svnclient, startrev, endrev)
            revcount = 0
            lc_updated = 'N'
            if( bUpdLineCount == True):
                lc_updated = 'Y'
            lastrevno = 0
            bAddDummy=True
            
            for revlog in svnloglist:
                logging.debug("Revision author:%s" % revlog.author)
                logging.debug("Revision date:%s" % revlog.date)
                logging.debug("Revision msg:%s" % revlog.message)
                revcount = revcount+1
                
                addedfiles, changedfiles, deletedfiles = revlog.changedFileCount()                
                if( revlog.isvalid() == True):
                    updcur.execute("INSERT into SVNLog(revno, commitdate, author, msg, addedfiles, changedfiles, deletedfiles) \
                                values(?, ?, ?, ?,?, ?, ?)",
                                (revlog.revno, revlog.date, revlog.author, revlog.message, addedfiles, changedfiles, deletedfiles))
                    
                    for change in revlog.getDiffLineCount(bUpdLineCount):
                        filename = change.filepath_unicode()
                        changetype = change.change_type()
                        linesadded = change.lc_added()
                        linesdeleted = change.lc_deleted()
                        copyfrompath,copyfromrev = change.copyfrom()
                        entry_type = 'R' #Real log entry.
                        pathtype = change.pathtype()
                        if(pathtype=='D'):
                            assert(filename.endswith('/')==True)
                        changepathid = self.getFilePathId(filename, updcur)
                        copyfromid = self.getFilePathId(copyfrompath,updcur)
                        if (changetype == 'R'):
                            logging.debug("Replace linecount (revno : %d): %s %d" % (revlog.revno, filename,linesadded))
                        updcur.execute("INSERT into SVNLogDetail(revno, changedpathid, changetype, copyfrompathid, copyfromrev, \
                                            linesadded, linesdeleted, lc_updated, pathtype, entrytype) \
                                    values(?, ?, ?, ?,?,?, ?,?,?,?)", (revlog.revno, changepathid, changetype, copyfromid, copyfromrev, \
                                            linesadded, linesdeleted, lc_updated, pathtype, entry_type))

                    if( bUpdLineCount == True and bAddDummy==True):
                        #dummy entries may add additional added/deleted file entries.
                        (addedfiles1, deletedfiles1) = self.addDummyLogDetail(revlog, querycur,updcur)
                        addedfiles = addedfiles+addedfiles1
                        deletedfiles = deletedfiles+deletedfiles1
                        updcur.execute("UPDATE SVNLog SET addedfiles=?, deletedfiles=? where revno=?",(addedfiles,deletedfiles,revlog.revno))
                            
                        #print "%d : %s : %s : %d : %d " % (revlog.revno, filename, changetype, linesadded, linesdeleted)
                    lastrevno = revlog.revno                    
                    #commit after every change
                    if( revcount % 10 == 0):
                        self.dbcon.commit()                        
                logging.debug("Number revisions converted : %d (Rev no : %d)" % (revcount, lastrevno))
                self.printVerbose("Number revisions converted : %d (Rev no : %d)" % (revcount, lastrevno))

            if( self.verbose == False):            
                print "Number revisions converted : %d (Rev no : %d)" % (revcount, lastrevno)
            querycur.close()
            updcur.close()    
                    
    def __createRevFileListForDir(self, revno, dirname, querycur, updcur):
        '''
        create the file list for a revision in a temporary table.
        '''
        assert(dirname.endswith('/'))
        updcur.execute('DROP TABLE IF EXISTS TempRevDirFileList')
        updcur.execute('DROP VIEW IF EXISTS TempRevDirFileListVw')
        updcur.execute('CREATE TEMP TABLE TempRevDirFileList(path text, pathid integer, addrevno integer)')
        updcur.execute('CREATE INDEX revdirfilelistidx ON TempRevDirFileList (addrevno ASC, path ASC)')
        sqlquery = 'SELECT DISTINCT SVNPaths.path, changedpathid, SVNLogDetail.revno FROM SVNLogDetail,SVNPaths WHERE \
                    pathtype="F" and SVNLogDetail.revno <=%d and (changetype== "A" or changetype== "R") \
                    and SVNLogDetail.changedpathid = SVNPaths.id and \
                    (SVNPaths.path like "%s%%" and SVNPaths.path != "%s")' \
                    % (revno,dirname,dirname)
        
        querycur.execute(sqlquery)
        for sourcepath, sourcepathid, addrevno in querycur:
            updcur.execute('INSERT INTO TempRevDirFileList(path, pathid, addrevno) \
                        VALUES(?,?,?)',(sourcepath, sourcepathid, addrevno))
        self.dbcon.commit()
        
        #Now delete the already deleted files from the file list.
        sqlquery = 'SELECT DISTINCT SVNPaths.path, SVNLogDetail.changedpathid, SVNLogDetail.revno FROM SVNLogDetail,SVNPaths \
                   WHERE pathtype="F" and SVNLogDetail.revno <=%d and changetype== "D" \
                   and SVNLogDetail.changedpathid = SVNPaths.id \
                    and (SVNPaths.path like "%s%%" and SVNPaths.path!= "%s")' \
                    % (revno,dirname,dirname)
        querycur.execute(sqlquery)
        for sourcepath, sourcepathid, delrevno in querycur:            
            updcur.execute('DELETE FROM TempRevDirFileList WHERE path=? and addrevno < ?',(sourcepath, delrevno))
        
        #in rare case there is a possibility of duplicate values in the TempRevFileList
        #hence try to create a temporary view to get the unique values
        updcur.execute('CREATE TEMP VIEW TempRevDirFileListVw AS SELECT DISTINCT \
            path, pathid, addrevno FROM TempRevDirFileList')
        self.dbcon.commit()
        
    def __createRevFileList(self, revlog, copied_dirlist, deleted_dirlist,querycur, updcur):
        '''
        create the file list for a revision for a specific directory in a temporary table.
        '''
        try:
            upd_del_dirlist = deleted_dirlist            
            updcur.execute('DROP TABLE IF EXISTS TempRevFileList')
            updcur.execute('DROP VIEW IF EXISTS TempRevFileListVw')
            updcur.execute('CREATE TEMP TABLE TempRevFileList(path text, addrevno integer, \
                        copyfrom_path text, copyfrom_pathid integer, copyfrom_rev integer)')
            updcur.execute('CREATE INDEX revfilelistidx ON TempRevFileList (addrevno ASC, path ASC)')
                
            for change in copied_dirlist:
                copiedfrom_path,copiedfrom_rev = change.copyfrom()
                #collect all files added to this directory.
                assert(copiedfrom_path.endswith('/') == change.filepath_unicode().endswith('/'))
                
                sqlquery = 'SELECT DISTINCT SVNPaths.path, changedpathid, revno FROM SVNLogDetail, SVNPaths \
                    WHERE pathtype="F" and revno <=%d and (changetype== "A" or changetype== "R") and \
                    SVNPaths.id = SVNLogDetail.changedpathid and \
                    (SVNPaths.path like "%s%%" and SVNPaths.path!= "%s") \
                    ' % (copiedfrom_rev,copiedfrom_path,copiedfrom_path)                
                querycur.execute(sqlquery)
                for sourcepath, sourcepathid, addrevno in querycur:
                    path = sourcepath.replace(copiedfrom_path, change.filepath_unicode())                    
                    updcur.execute('INSERT INTO TempRevFileList(path, addrevno, copyfrom_path, copyfrom_pathid,copyfrom_rev) \
                        VALUES(?,?,?,?,?)',(path, addrevno, sourcepath,sourcepathid, copiedfrom_rev))
            self.dbcon.commit()
            
            #Now delete the already deleted files from the file list.                
            for change in copied_dirlist:
                copiedfrom_path,copiedfrom_rev = change.copyfrom()
                sqlquery = 'SELECT DISTINCT SVNPaths.path, changedpathid, revno FROM SVNLogDetail,SVNPaths WHERE \
                    pathtype="F" and revno <=%d and changetype== "D" and \
                    SVNPaths.id = SVNLogDetail.changedpathid and \
                    (SVNPaths.path like "%s%%" and SVNPaths.path != "%s")'% (copiedfrom_rev,copiedfrom_path,copiedfrom_path)
                querycur.execute(sqlquery)
                for sourcepath, sourcepathid, delrevno in querycur:
                    path = sourcepath.replace(copiedfrom_path, change.filepath_unicode())                    
                    updcur.execute('DELETE FROM TempRevFileList WHERE path=? and addrevno < ?',(path, delrevno))
                    
            self.dbcon.commit()
            
            #Now delete the entries for which 'real' entry is already created in
            #this 'revision' update.
            for change_entry in revlog.getFileChangeEntries():
                filepath = change_entry.filepath()
                updcur.execute('DELETE FROM TempRevFileList WHERE path=?',(filepath,))
                
            upd_del_dirlist = []        
            for change in deleted_dirlist:
                #first check if 'deleted' directory entry is there in the revision filelist
                #if yes, remove those rows.
                querycur.execute('SELECT count(*) FROM TempRevFileList WHERE path like "%s%%"' %change.filepath())
                count = int(querycur.fetchone()[0])
                if( count > 0):
                    updcur.execute('DELETE FROM TempRevFileList WHERE path like "%s%%"'%change.filepath())
                else:
                    #if deletion path is not there in the addition path, it has to be
                    #handled seperately. Hence add it into different list
                    upd_del_dirlist.append(change)
        
            #in rare case there is a possibility of duplicate values in the TempRevFileList
            #hence try to create a temporary view to get the unique values
            updcur.execute('CREATE TEMP VIEW TempRevFileListVw AS SELECT DISTINCT \
                path, addrevno, copyfrom_path, copyfrom_pathid,copyfrom_rev FROM TempRevFileList \
                group by path having addrevno=max(addrevno)')
                    
            self.dbcon.commit()
            
        except:
            logging.exception("Found error while getting file list for revision")
            
        return(upd_del_dirlist)
        
    def __addDummyAdditionDetails(self, revno, querycur, updcur):        
        addedfiles  = 0
        path_type = 'F'                                    
        changetype = 'A'
        entry_type = 'D'
        lc_updated = 'Y'
        total_lc_added = 0

        querycur.execute("SELECT count(*) from TempRevFileListVw")
        logging.debug("Revision file count = %d" % querycur.fetchone()[0])
        
        querycur.execute("SELECT * from TempRevFileListVw")
        for changedpath, addrevno, copyfrompath, copyfrompathid, copyfromrev in querycur.fetchall():                    
            querycur.execute("select sum(linesadded), sum(linesdeleted) from SVNLogDetail \
                    where revno <= ? and changedpathid ==(select id from SVNPaths where path== ?) group by changedpathid",
                     (copyfromrev, copyfrompath))
    
            row = querycur.fetchone()
            #set lines added to current line count
            lc_added = 0
            if row is not None:
                lc_added = row[0]-row[1]
                        
            if( lc_added < 0):
                logging.error("Found negative linecount for %s(rev %d)" % (copyfrompath,copyfromrev))
                lc_added = 0
            #set the lines deleted = 0
            lc_deleted = 0

            total_lc_added = total_lc_added+lc_added
            #logging.debug("\tadded dummy addition entry for path %s linecount=%d" % (changedpath,lc_added))
            changedpathid = self.getFilePathId(changedpath, querycur)
            copyfrompathid = self.getFilePathId(copyfrompath, querycur)
            assert(path_type != 'U')
            updcur.execute("INSERT into SVNLogDetail(revno, changedpathid, changetype, copyfrompathid, copyfromrev, \
                                    linesadded, linesdeleted, entrytype, pathtype, lc_updated) \
                            values(?, ?, ?, ?,?,?, ?,?,?,?)", (revno, changedpathid, changetype, copyfrompathid, copyfromrev, \
                                    lc_added, lc_deleted, entry_type,path_type,lc_updated))
            addedfiles = addedfiles+1                    
        #Now commit the changes
        self.dbcon.commit()
        logging.debug("\t Total dummy line count : %d" % total_lc_added)
        return addedfiles
    
    def __addDummyDeletionDetails(self, revno, deleted_dir, querycur, updcur):
        deletedfiles = 0
        addedfiles  = 0
        path_type = 'F'
        #set lines added to 0
        lc_added = 0
        changetype = 'D'
        entry_type = 'D'
        lc_updated = 'Y'
        
        assert(deleted_dir.endswith('/'))
        #now query the deleted folders from the sqlite database and get the
        #file list
        logging.debug("Updating dummy file deletion entries for path %s" % deleted_dir)
        self.__createRevFileListForDir(revno, deleted_dir, querycur, updcur)
                
        querycur.execute('SELECT path FROM TempRevDirFileListVw')
        for changedpath, in querycur.fetchall():
            #logging.debug("\tDummy file deletion entries for path %s" % changedpath)      
            querycur.execute('select sum(linesadded), sum(linesdeleted)  from SVNLogDetail \
                    where revno <= ? and changedpathid ==(select id from SVNPaths where path== ?) group by changedpathid',
                             (revno,changedpath))
        
            row = querycur.fetchone()
            lc_deleted = 0
            if row != None:                
                #set lines deleted to current line count
                lc_deleted = row[0]-row[1]                
            if( lc_deleted < 0):
                logging.error("Found negative linecount for %s(rev %d)" % (changedpath,revno))
                lc_deleted = 0
        
            changedpathid = self.getFilePathId(changedpath, updcur)
            updcur.execute("INSERT into SVNLogDetail(revno, changedpathid, changetype,  \
                                    linesadded, linesdeleted, entrytype, pathtype, lc_updated) \
                            values(?, ?,?,?, ?,?,?,?)", (revno, changedpathid, changetype,  \
                                    lc_added, lc_deleted, entry_type,path_type,lc_updated))
            deletedfiles = deletedfiles+1
        self.dbcon.commit()
        return deletedfiles

    def addDummyLogDetail(self,revlog, querycur, updcur):
        '''
        add dummy log detail entries for getting the correct line count data in case of tagging/branching and deleting the directories.
        '''        
        addedfiles = 0
        deletedfiles = 0
        
        copied_dirlist = revlog.getCopiedDirs()
        deleted_dirlist = revlog.getDeletedDirs()
        
        if( len(copied_dirlist) > 0 or len(deleted_dirlist) > 0):
            #since we may have to query the existing data. Commit the changes first.
            self.dbcon.commit()
            #Now create list of file names for adding dummy entries. There is
            #no  need to add dummy entries for directories.
            if( len(copied_dirlist) > 0):
                #now update the additions    
                #Path type is directory then dummy entries are required.
                #For file type, 'real' entries will get creaetd
                logging.debug("Adding dummy file addition entries")
                deleted_dirlist = self.__createRevFileList(revlog, copied_dirlist, deleted_dirlist,
                                    querycur, updcur)
                addedfiles  = self.__addDummyAdditionDetails(revlog.revno, querycur, updcur)                
            if len(deleted_dirlist) > 0:
                logging.debug("Adding dummy file deletion entries")
                for deleted_dir in deleted_dirlist:
                    deletedfiles = deletedfiles+ self.__addDummyDeletionDetails(revlog.revno, deleted_dir.filepath(), querycur, updcur)
                
        #if( revlog.revno == 373):
        #    from sys import exit
        #    exit(0)
        return(addedfiles, deletedfiles)
            
    def UpdateLineCountData(self):
        self.initdb()
        try:        
            self.__updateLineCountData()
        except Exception, expinst:            
            logging.exception("Error %s" % expinst)
            print "Error %s" % expinst            
        self.closedb()
        
    def __updateLineCountData(self):
        '''Update the line count data in SVNLogDetail where lc_update flag is 'N'.
        This function is to be used with incremental update of only 'line count' data.
        '''
        #first create temporary table from SVNLogDetail where only the lc_updated status is 'N'
        #Set the autocommit on so that update cursor inside the another cursor loop works.
        self.dbcon.isolation_level = None
        cur = self.dbcon.cursor()        
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS LCUpdateStatus \
                    as select revno, changedpath, changetype from SVNLogDetail where lc_updated='N'")
        self.dbcon.commit()
        cur.execute("select revno, changedpath, changetype from LCUpdateStatus")
                
        for revno, changedpath, changetype in cur:
            linesadded =0
            linesdeleted = 0
            self.printVerbose("getting diff count for %d:%s" % (revno, changedpath))
            
            linesadded, linesdeleted = self.svnclient.getDiffLineCountForPath(revno, changedpath, changetype)
            sqlquery = "Update SVNLogDetail Set linesadded=%d, linesdeleted=%d, lc_updated='Y' \
                    where revno=%d and changedpath='%s'" %(linesadded,linesdeleted, revno,changedpath)
            self.dbcon.execute(sqlquery)            
        
        cur.close()
        self.dbcon.commit()
        
    def CreateTables(self):
        cur = self.dbcon.cursor()
        cur.execute("create table if not exists SVNLog(revno integer, commitdate timestamp, author text, msg text, \
                            addedfiles integer, changedfiles integer, deletedfiles integer)")
        cur.execute("create table if not exists SVNLogDetail(revno integer, changedpathid integer, changetype text, copyfrompathid integer, copyfromrev integer, \
                    pathtype text, linesadded integer, linesdeleted integer, lc_updated char, entrytype char)")
        cur.execute("CREATE TABLE IF NOT EXISTS SVNPaths(id INTEGER PRIMARY KEY AUTOINCREMENT, path text, relpathid INTEGER DEFAULT null)")
        try:
                #create VIEW IF NOT EXISTS was not supported in default sqlite version with Python 2.5
                cur.execute("CREATE VIEW SVNLogDetailVw AS select SVNLogDetail.*, ChangedPaths.path as changedpath, CopyFromPaths.path as copyfrompath \
                    from SVNLogDetail LEFT JOIN SVNPaths as ChangedPaths on SVNLogDetail.changedpathid=ChangedPaths.id \
                    LEFT JOIN SVNPaths as CopyFromPaths on SVNLogDetail.copyfrompathid=CopyFromPaths.id")
        except:
                #you will get an exception if the view exists. In that case nothing to do. Just continue.
                pass
        #lc_updated - Y means line count data is updated.
        #lc_updated - N means line count data is not updated. This flag can be used to update
        #line count data later        
        cur.execute("CREATE INDEX if not exists svnlogrevnoidx ON SVNLog (revno ASC)")
        cur.execute("CREATE INDEX if not exists svnlogdtlrevnoidx ON SVNLogDetail (revno ASC)")
        cur.execute("CREATE INDEX if not exists svnlogdtlchangepathidx ON SVNLogDetail (changedpathid ASC)")
        cur.execute("CREATE INDEX if not exists svnlogdtlcopypathidx ON SVNLogDetail (copyfrompathid ASC)")
        cur.execute("CREATE INDEX IF NOT EXISTS svnpathidx ON SVNPaths (path ASC)")
        self.dbcon.commit()
        
        #Table structure is changed slightly. I have added a new column in SVNLogDetail table.
        #Use the following sql to alter the old tables
        #ALTER TABLE SVNLogDetail ADD COLUMN lc_updated char
        #update SVNLogDetail set lc_updated ='Y' ## Use 'Y' or 'N' as appropriate.

        #because of some bug in old code sometimes path contains '//' or '.'. Uncomment the line to Fix such paths
        #self.__fixPaths()
        
    def __fixPaths(self):
        '''
        because of some bug in old code sometimes the path contains '//' or '.' etc. Fix such paths
        '''
        cur = self.dbcon.cursor()
        cur.execute("select * from svnpaths")
        pathstofix = []
        for id, path in cur:
            nrmpath = svnlogiter.normurlpath(path)
            if( nrmpath != path):
                logging.debug("fixing path for %s to %s"%(path, nrmpath))
                pathstofix.append((id,nrmpath))
        for id, path in pathstofix:
            cur.execute('update svnpaths set path=? where id=?',(path, id))
        self.dbcon.commit()
        #Now fix the duplicate entries created after normalization
        cur = self.dbcon.cursor()
        updcur = self.dbcon.cursor()
        cur.execute("SELECT count(path) as pathcnt, path FROM svnpaths group by path having pathcnt > 1")
        duppathlist = [path for cnt, path in cur]
        for duppath in duppathlist:
            #query the ids for this path
            cur.execute("SELECT * FROM svnpaths WHERE path = ? order by id", (duppath,))
            correctid, duppath1 = cur.fetchone()
            print "updating path %s" % duppath
            for pathid, duppath1 in cur:
                updcur.execute("UPDATE SVNLogDetail SET changedpathid=? where changedpathid=?", (correctid,pathid))
                updcur.execute("UPDATE SVNLogDetail SET copyfrompathid=? where copyfrompathid=?", (correctid,pathid))
                updcur.execute("DELETE FROM svnpaths where id=?", (pathid,))
            self.dbcon.commit()
        #if paths are fixed. Then drop the activity hotness table so that it gets rebuilt next time.
        if( len(duppathlist) > 0):            
            updcur.execute("DROP TABLE IF EXISTS ActivityHotness")        
            self.dbcon.commit()        
            print "fixed paths"
        
    def printVerbose(self, msg):
        logging.info(msg)
        if( self.verbose==True):
            print msg            
                    
def getLogfileName(sqlitedbpath):
    '''
    create log file in using the directory path from the sqlitedbpath
    '''
    dir, file = os.path.split(sqlitedbpath)
    logfile = os.path.join(dir, 'svnlog2sqlite.log')
    return(logfile)
    
def parse_svndate(svndatestr):
    '''
    Using simple dates '{YEAR-MONTH-DAY}' as defined in http://svnbook.red-bean.com/en/1.5/svn-book.html#svn.tour.revs.dates
    '''
    svndatestr = svndatestr.strip()
    svndatestr = svndatestr.strip('{}')
    svndatestr = svndatestr.split('-')    

    year = int(svndatestr[0])
    month = int(svndatestr[1])
    day = int(svndatestr[2])

    #convert the time to typical unix timestamp for seconds after epoch
    svntime = datetime.datetime(year, month, day)
    svntime = calendar.timegm(svntime.utctimetuple())
    
    return(svntime)

def getquotedurl(url):
    '''
    svn repo url specified on the command line can contain specs, special etc. We
    have to quote them to that svn log client works on a valid url.
    '''
    import urllib
    import urlparse
    urlparams = list(urlparse.urlsplit(url, 'http'))
    urlparams[2] = urllib.quote(urlparams[2])
    
    return(urlparse.urlunsplit(urlparams))
    
def RunMain():
    usage = "usage: %prog [options] <svnrepo root url> <sqlitedbpath>"
    parser = OptionParser(usage)
    parser.set_defaults(updlinecount=False)

    parser.add_option("-l", "--linecount", action="store_true", dest="updlinecount", default=False,
                      help="extract/update changed line count (True/False). Default is False")
    parser.add_option("-g", "--log", action="store_true", dest="enablelogging", default=False,
                      help="Enable logging during the execution(True/False). Name of generate logfile is svnlog2sqlite.log.")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                      help="Enable verbose output. Default is False")
    parser.add_option("-u", "--username", dest="username",default=None, action="store", type="string",
                      help="username to be used for repository authentication")
    parser.add_option("-p", "--password", dest="password",default=None, action="store", type="string",
                      help="password to be used for repository authentication")
    (options, args) = parser.parse_args()
    
    if( len(args) < 2 ):
        print "Invalid number of arguments. Use svnlog2sqlite.py --help to see the details."    
    else:
        svnrepopath = args[0]
        sqlitedbpath = args[1]
        svnrevstartdate = None
        svnrevenddate = None
        
        if( len(args) > 3):
            #more than two argument then start date and end date is specified.
            svnrevstartdate = parse_svndate(args[2])
            svnrevenddate = parse_svndate(args[3])
            
        if( not svnrepopath.endswith('/')):
            svnrepopath = svnrepopath+'/'
        
        svnrepopath = getquotedurl(svnrepopath)
        
        print "Updating the subversion log"
        print "Repository : " + svnrepopath            
        print "SVN Log database filepath : %s" % sqlitedbpath
        print "Extract Changed Line Count : %s" % options.updlinecount
        if( not options.updlinecount):
            print "\t\tplease use -l option. if you want to extract linecount information."
        if( svnrevstartdate):
            print "Repository startdate: %s" % (svnrevstartdate)
        if( svnrevenddate):
            print "Repository enddate: %s" % (svnrevenddate)
        
        if(options.enablelogging==True):
            logfile = getLogfileName(sqlitedbpath)
            logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    filename=logfile,
                    filemode='w')
            print "Debug Logging to file %s" % logfile

        conv = None            
        conv = SVNLog2Sqlite(svnrepopath, sqlitedbpath,verbose=options.verbose, username=options.username, password=options.password)
        conv.convert(svnrevstartdate, svnrevenddate, options.updlinecount)        
        
if( __name__ == "__main__"):
    RunMain()
    
