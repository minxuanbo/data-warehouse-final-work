var pageSize = 10;
var totalCount = 0;
var currentPage = 0;
var showCurrentPage = 0;
$(function () {
  var styleIndex = $('#styleIndex').val();
  var i = parseInt(styleIndex) - 1;
  var obj = $('.header-nav').find('li');
  obj.each(function () {
    $(this).find('a').removeClass('curr');
  });
  obj.eq(i).find('a').addClass('curr');

  totalCount = $('#totalJobCount').val();
  initDate();

  $('.search-btn').click(function () {
    getJobCountForParams();
    /**挖掘用户输入热词*/
    /* addHotWords();*/
  });

  /**绑定回车搜索*/
  $("#search-key").bind('keypress', function (event) {
    if (event.keyCode == "13") {
      getJobCountForParams();
      return false;
    }
  });

  /**热词渲染,默认top4热词*/
  setTopHotWords(4);
});

function initDate() {
  getAllParams();
}

/*
 * 渲染列表中职位类别及工作地点
 */
function getAllParams() {
  jQuery.ajax({
    type: "POST",
    url: "/web/job/job_allparams",
    data: {},
    success: function (data) {
      if (data != null) {
        var jsonData = eval('(' + data + ')');
        // 业务单元
        var deptList = jsonData.deptList;
        if (null != deptList) {
          var deptLength = deptList.length;
          if (deptLength > 0) {
            var depHtm = '<ul>';
            for (var i = 0; i < deptLength; i++) {
              depHtm += '<li class=\"drop-item\"><input type="checkbox" class="param_li" name="depCode_li" value="' + deptList[i].dictCode + '"><label for="">' + deptList[i].dictName + '</label></li>';
            }
            depHtm += '</ul>';
            $('#depCode').append(depHtm);
          }
        }
        
        
        //职位类别
        var jobTypeList = jsonData.jobTypeList;
        if (null != jobTypeList) {
          var jtLength = jobTypeList.length;
          if (jtLength > 0) {
            var jtHtm = '<ul><li class=\"drop-item\"><input type="checkbox" class="select-all-params"><label for="">全部</label></li>';
            for (var i = 0; i < jtLength; i++) {
              jtHtm += '<li class=\"drop-item\"><input type="checkbox" class="param_li" name="jobtype_li" value="' + jobTypeList[i].dictDataCode + '"><label for="">' + jobTypeList[i].dictDataName + '</label></li>';
            }
            jtHtm += '</ul>';
            $('#jobType').append(jtHtm);
          }
        }

        //工作地点
        var workCityList = jsonData.workCityList;
        if (null != workCityList) {
          var wcLength = workCityList.length;
          if (wcLength > 0) {
            var wcHtm = '<ul><li class=\"drop-item\"><input type="checkbox" class="select-all-params"><label for="">全部</label></li>';
            for (var i = 0; i < wcLength; i++) {
              wcHtm += '<li class=\"drop-item\"><input type="checkbox" class="param_li" name="workcity_li" value="' + workCityList[i].dictCode + '"><label for="">' + workCityList[i].dictName + '</label></li>';
            }
            wcHtm += '</ul>';
            $('#workCity').append(wcHtm);
          }
        }
      }
      initSelected();
      initPage();
      selectJobCheckbox();

    },
    error: function () {
      initSelected();
      initPage();
      selectJobCheckbox();
    }
  });
}

function initSelected() {
  var jobTypeParam = $('#jobTypeParam').val();
  var workCityParam = $('#workCityParam').val();
  var depParam = $('#deptCodeParam').val();

  if (depParam != null
      && depParam != '') {
    $("input[name='depCode_li']").each(function () {
      var depCode = $(this).val();
      if (depParam == depCode) {
        $(this).prop("checked", true);
      }
    });
  }
  
  if (jobTypeParam != null
    && jobTypeParam != '') {
    $("input[name='jobtype_li']").each(function () {
      var jobTypeCode = $(this).val();
      if (jobTypeParam == jobTypeCode) {
        $(this).prop("checked", true);
      }
    });
  }
  if (workCityParam != null
    && workCityParam != '') {
    $("input[name='workcity_li']").each(function () {
      var workcityCode = $(this).val();
      if (workCityParam == workcityCode) {
        $(this).prop("checked", true);
      }
    });
  }
}

/*
 * 批量选择或反选checkbox
 */
function preJobCheckbox(boxs, select) {
  boxs.each(function () {
    $(this).prop('checked', select);
  });
}
/*
 * checkbox选择事件
 */
function selectJobCheckbox() {
  //全选/反选
  $('.select-all-params').click(function () {
    var $select = $(this).parents('.sug-dropdown');
    var isChecked = $(this).prop('checked');
    var $checkboxs = $select.find('li input[type=checkbox]');
    preJobCheckbox($checkboxs, isChecked);
    getJobCountForParams();
  });

  //单个选择
  $('.param_li').click(function () {
    getJobCountForParams();
  });
}

function getJobCountForParams() {
  //搜索框
  var jobSearch = $('.search-ipt').val();

  //选中的工作地点
  var workCityArr = new Array();
  var index = 0;
  $("input[name='workcity_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      workCityArr[index++] = $(this).val();
    }
  });
  var workCityJson = JSON.stringify(workCityArr);

  //选中的职位类别
  var jobTypeArr = new Array();
  var iindex = 0;
  $("input[name='jobtype_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      jobTypeArr[iindex++] = $(this).val();
    }
  });
  var jobTypeJson = JSON.stringify(jobTypeArr);

  // 业务单元
  var depTypeArr = new Array();
  var dindex = 0;
  $("input[name='depCode_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      depTypeArr[dindex++] = $(this).val();
    }
  });
  var depTypeJson = JSON.stringify(depTypeArr);
  
  jQuery.ajax({
    type: "POST",
    url: "/web/job/job_count",
    data: {
      workCityJson: workCityJson,
      jobTypeJson: jobTypeJson,
      jobSearch: jobSearch,
      depTypeJson: depTypeJson
    },
    success: function (data) {
      $('#totalJobCount').val(data);
      totalCount = data;
      currentPage = 0;
      initPage();
    },
    error: function () {
    }
  });
}

/*
 * 初始化分页
 */
function initPage() {
  if (totalCount > 0) {
    $('.page-area').empty();
    var pageHtm = '<div class="page-skip">'
      + '<span class="skip">跳至<input type="text" class="skip_page" name="">页</span>'
      + '<a href="javascript:showSkipPage()" class="sure-btn">确定</a></div>'
      + '<div id="pagination" class="pagination"></div>';
    $('.page-area').append(pageHtm);

    //分页
    seajs.use('/zhaopin/js/ui/pagination', function () {
      $("#pagination").pagination({
        total: totalCount,
        pageSize: pageSize,           // 每页显示的条目数
        currentPage: currentPage,
        viewSize: 4,      // 连续分页主体部分显示的分页条目数
        edgeSize: 1,         // 与起点的间隔
        prevText: '<',               // “上一页”分页按钮上显示的文字
        nextText: '>',               // “下一页”分页按钮上显示的文字
        linkTo: 'javascript:showJobInfosIndex();',      // 分页的链接,默认是"#"
        ellipseText: '...',          // 省略的页数用什么文字表示,默认是"..."
        callback: function (index, el) {
          //console.log(index);
        }
      });
    });
    findJobInfoContents(currentPage + 1);
  } else {
    var emptyHtm = '<div class="empty"><div class="empty-img"><img src="/zhaopin/css/i/404/icon8.png"></div>'
      + '<div class="empty-txt">查询不到岗位信息，请更换查询条件或刷新重试！</div>'
      + '<div class="empty-btn"><a href="/web/job/job_info_list/3">刷新重试</a></div></div>';
    $('.table-main').empty();
    $('.page-area').empty();
    $('.table-main').append(emptyHtm);
  }
}

/*
 * 分页链接
 */
function showJobInfosIndex() {
  var icurrentPage = $('.current').text();
  if (icurrentPage.length > 1) {
    icurrentPage = icurrentPage.replace(/>|</, "");
  }
  findJobInfoContents(icurrentPage);
}

/*
 * 输入框输入页码
 */
function showSkipPage() {
  var icurrentPage = $('.skip_page').val();
  if (!/^[0-9]*[1-9][0-9]*$/.test(icurrentPage)) {
    errorTip('请输入正确页码');
    return;
  }
  getSkipPageCount(icurrentPage);
}
function getSkipPageCount(icurrentPage) {
  //搜索框
  var jobSearch = $('.search-ipt').val();

  //选中的工作地点
  var workCityArr = new Array();
  var index = 0;
  $("input[name='workcity_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      workCityArr[index++] = $(this).val();
    }
  });
  var workCityJson = JSON.stringify(workCityArr);

  //选中的职位类别
  var jobTypeArr = new Array();
  var iindex = 0;
  $("input[name='jobtype_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      jobTypeArr[iindex++] = $(this).val();
    }
  });
  var jobTypeJson = JSON.stringify(jobTypeArr);

  jQuery.ajax({
    type: "POST",
    url: "/web/job/job_count",
    data: {
      workCityJson: workCityJson,
      jobTypeJson: jobTypeJson,
      jobSearch: jobSearch
    },
    success: function (data) {
      $('#totalJobCount').val(data);
      totalCount = data;
      var skipCurrentPage = 0;
      var pageNum = Math.ceil(totalCount / pageSize);
      if (icurrentPage > pageNum) {
        skipCurrentPage = pageNum - 1;
      } else {
        skipCurrentPage = icurrentPage - 1;
      }
      seajs.use('/zhaopin/js/ui/pagination', function () {
        $("#pagination").pagination({
          total: totalCount,
          pageSize: pageSize,           // 每页显示的条目数
          currentPage: skipCurrentPage,
          viewSize: 4,      // 连续分页主体部分显示的分页条目数
          edgeSize: 1,         // 与起点的间隔
          prevText: '<',               // “上一页”分页按钮上显示的文字
          nextText: '>',               // “下一页”分页按钮上显示的文字
          linkTo: 'javascript:showJobInfosIndex();',      // 分页的链接,默认是"#"
          ellipseText: '...',          // 省略的页数用什么文字表示,默认是"..."
          callback: function (index, el) {
            //console.log(index);
          }
        });
      });
      findJobInfoContents(icurrentPage)
    },
    error: function () {
    }
  });
}

/*
 * 查询当前分页的岗位内容list
 */
function findJobInfoContents(icurrentPage) {
  showCurrentPage = icurrentPage;
  //搜索框
  var jobSearch = $('.search-ipt').val();

  //选中的工作城市
  var workCityArr = new Array();
  var index = 0;
  $("input[name='workcity_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      workCityArr[index++] = $(this).val();
    }
  });
  var workCityJson = JSON.stringify(workCityArr);
  //选中的职位类别
  var jobTypeArr = new Array();
  var iindex = 0;
  $("input[name='jobtype_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      jobTypeArr[iindex++] = $(this).val();
    }
  });
  var jobTypeJson = JSON.stringify(jobTypeArr);
  
  // 选择业务单元
  var depTypeArr = new Array();
  var dindex = 0;
  $("input[name='depCode_li']:checkbox").each(function () {
    if ($(this).is(":checked")) {
      depTypeArr[dindex++] = $(this).val();
    }
  });
  var depTypeJson = JSON.stringify(depTypeArr);
  
  jQuery.ajax({
    type: "POST",
    url: "/web/job/job_list",
    data: {
      pageIndex: icurrentPage,
      pageSize: pageSize,
      workCityJson: workCityJson,
      jobTypeJson: jobTypeJson,
      jobSearch: jobSearch,
      depTypeJson: depTypeJson
    },
    success: function (data) {
      if (data != null) {
        var htm = '';
        var jsonData = eval('(' + data + ')');
        var length = jsonData.length;
        $('.table-main').empty();
        for (var i = 0; i < length; i++) {
          //处理职位描述
          var workContentHtm = '';
          var workContent = jsonData[i].workContent;
          var workContentArr;
          if (null != workContent && workContent != "") {
            workContentArr = workContent.split(/\n/);
            for (var j = 0; j < workContentArr.length; j++) {
              workContentHtm += '<p>' + workContentArr[j] + '</p>';
            }
          }
          //处理职位要求
          var qualificationHtm = '';
          var qualification = jsonData[i].qualification;
          var qualificationArr;
          if (null != qualification && qualification != "") {
            qualificationArr = qualification.split(/\n/);
            for (var k = 0; k < qualificationArr.length; k++) {
              qualificationHtm += '<p>' + qualificationArr[k] + '</p>';
            }
          }


          //职位收藏状态
          var jcHtm = '<span>';
          var jobCollectionId = jsonData[i].positionCollectionId;
          if (null != jobCollectionId && jobCollectionId != 0) {
            jcHtm += '<i class="star-icon light"></i></span>';
          } else {
            jcHtm += '<i class="star-icon"></i></span>';
          }

          var positionName = '';
          if (null != jsonData[i].positionNameOpen) {
            positionName = jsonData[i].positionNameOpen;
          }
          var jobType = '';
          if (null != jsonData[i].jobType) {
            jobType = jsonData[i].jobType;
          }

          var workCity = '';
          if (null != jsonData[i].workCity) {
            workCity = jsonData[i].workCity;
          }

          var publishTime = '';
          if (null != jsonData[i].publishTime) {
            publishTime = (new Date(jsonData[i].publishTime)).format('yyyy-MM-dd');
          }

          var shortPositionName = '';
          if(null != positionName && positionName.length > 18){
            shortPositionName = positionName.substr(0,18) + '...';
          }else{
            shortPositionName = positionName;
          }
          
          // 业务单元
          var depName = '';
          if (null != jsonData[i].positionDeptName) {
            depName = jsonData[i].positionDeptName;
          } else {
            depName = '--';
          }

          htm += '<div class="line">'
            + '<div class="info">'
            + '<input type="hidden" id="requemtId" value="' + jsonData[i].requirementId + '"/>'
              + '<span class="post ta-l" title="' + positionName + '">' + shortPositionName + '<b class="drop-down"></b></span>'
            + '<span class="sel">' + depName + '</span>'
            + '<span class="sel">' + jobType + '</span>'
            + '<span class="sel">' + workCity + '</span>'
            + '<span>' + publishTime + '</span>'
            + jcHtm
            + '<span><a href="javascript:;" class="apply-btn" recRequirementId="' + jsonData[i].requirementId + '" positionId=" ' + jsonData[i].positionId + '" onclick="applyBtn(this)">立即申请</a></span>'
            + '</div>'
            + '<div class="detail">'
            + '<div class="par"><h3>岗位描述：</h3>' + workContentHtm + '</div>'
            + '<div class="par"><h3>任职要求：</h3>' + qualificationHtm + '</div>'
            + '</div>'
            + '</div>';
        }
        $('.table-main').append(htm);
        jobCollectClick();
      }
    },
    error: function () {
      errorTip('获取职位列表失败！');
    }
  });
}

var storeFlag = true;
function jobCollectClick() {
  var isLogin = $('#isLogin').val();
  $('.star-icon').click(function () {
    $this = $(this);
    if ($this.hasClass('light')) {
      deleteJobCollection($this);
      //删除收藏
      //$this.removeClass('light');
    } else {
      //添加收藏
      if (isLogin == '0') {
        //未登录，进入登录页面
        submitTip("您尚未登录，请登录后再收藏！", locatLogin);
      } else {
        if (!storeFlag) return;
        $this.before('<div class="toastl "><span>职位收藏中...</span><i></i></div>');
        storeFlag = false;
        setTimeout(function () {
          addJobCollection($this);
        }, 1000);
        //$this.addClass('light');
      }
    }
  });
}

//加入职位收藏
function addJobCollection(obj) {
  var requementId = obj.parents('.info').find('#requemtId').val();
  jQuery.ajax({
    type: "POST",
    url: "/web/jobCollect/job_collection_add",
    data: {
      requementId: requementId
    },
    success: function (data) {
      var jsonData = eval('(' + data + ')');
      if (jsonData.isJobLogin == 'yes') {
        findJobInfoContents(showCurrentPage);
        storeFlag = true;
        //成功弹窗
        $('.toast.success').show();
        setTimeout(function () {
          $('.toast.success').hide();
        }, 1000);
      } else {
        //未登录，进入登录页面
        location.href = '/web/job_info_list/3';
      }
    },
    error: function () {
      storeFlag = true;
      errorTip('职位添加收藏失败！');
    }
  });
}
//取消职位收藏
function deleteJobCollection(obj) {
  var requementId = obj.parents('.info').find('#requemtId').val();
  jQuery.ajax({
    type: "POST",
    url: "/web/jobCollect/job_collection_remove",
    data: {
      requementId: requementId
    },
    success: function (data) {
      var jsonData = eval('(' + data + ')');
      if (jsonData.isJobLogin == 'yes') {
        findJobInfoContents(showCurrentPage);
        //取消弹窗
        $('.toast.cancel').show();
        setTimeout(function () {
          $('.toast.cancel').hide();
        }, 1000);
      } else {
        //未登录，进入登录页面
        location.href = '/login'
      }
    },
    error: function () {
      errorTip('职位取消收藏失败！');
    }
  });
}

//申请职位
function applyBtn(element) {
  var isLogin = $('#isLogin').val();
  if (isLogin == '0') {
    //未登录，进入登录页面
    submitTip("您尚未登录，请登录后再申请！", locatLogin);
  } else {
    var recRequirementId = $(element).attr('recRequirementId');
    var positionId = $(element).attr('positionId');
    $.ajax({
      url: '/web/ucenter/jobcollection_send',
      type: "post",
      data: {
        recRequirementId: recRequirementId,
        positionId: positionId
      },
      success: function (data) {
        if (data.opertor == false) {
          errorTip(data.message);
        } else if (data.opertor == true) {
            singleAccept(data.message);
        } else {
          errorTip('申请失败！');
        }
        findJobInfoContents(showCurrentPage);
      },
      error: function () {
        errorTip('申请失败！');
      }
    });
  }
}

function locatLogin() {
  location.href = '/web/job_info_list/3';
}

/**设置热词*/
function setTopHotWords(top) {
  $.ajax({
    url: '/web/get_top_hotWords',
    type: "post",
    data: {top: top},
    success: function (data) {
      if (data != null) {
        var jsonData = eval('(' + data + ')');
        var length = jsonData.length;
        $('.hot-words').empty();
        var html = "热门搜索：";
        for (var i = 0; i < length; i++) {
          html = html + '<a href="javascript:;" class="key-words" id="' + jsonData[i].hotWords + '">' + jsonData[i].hotWords + '</a>';
        }
        $('.hot-words').html(html);
        $('.hot-words .key-words').click(function (event) {
          var param = $(event.target).attr('id');
          $('.search-ipt').val(param);
          getJobCountForParams();
        });
      }
    }
  });
}

function addHotWords() {
  var hotWords = $('.search-ipt').val();
  $.ajax({
    url: '/web/add_hotWords',
    type: "post",
    data: {hotWords: hotWords},
    success: function () {
    }
  });
}


function acceptTip(tip) {
  seajs.use('/zhaopin/js/ui/dialog', function () {
    var dialogHtm = '<div class="addsubmit"><div class="add-icon suc-face"></div><p>'
      + tip + '</p></div>';
    var $dialog = $.confirm({
      title: '提示',
      width: 450,
      btnCelText: '关闭',
      containerCls: 'sty-thick single-btn',
      content: dialogHtm
    });
  });
}

function acceptTipNow(tip) {
    seajs.use('/zhaopin/js/ui/dialog', function () {
        var dialogHtm = '<div class="addsubmit"><div class="add-icon suc-face"></div><p>'
            + tip + '</p></div>';
        var $dialog = $.confirm({
            title: '提示',
            width: 450,
            btnCelText: '关闭',
            containerCls: 'sty-thick single-btn',
            content: dialogHtm
        });
    });
}
